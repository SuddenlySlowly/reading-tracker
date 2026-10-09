#!/usr/bin/env python3
"""독서 기록 data.json 업데이트 도우미.

사용 예:
  python3 update.py log --book '폭풍이 온다' --page 150 [--date 2026-10-10] [--note '메모']
  python3 update.py log --book '폭풍이 온다' --from 103 --page 150      # 범위로 기록
  python3 update.py add-book --title '코스모스' --author '칼 세이건' --pages 720 [--status plan|reading|done|stop] [--start YYYY-MM-DD]
  python3 update.py set --book '폭풍이 온다' --pages 344 [--status done] [--author ...] [--rating 5] [--memo ...] [--start ...] [--end ...]
  python3 update.py set --book '폭풍이 온다' --cover 'https://.../cover.jpg'   # 또는 로컬 파일 경로 → covers/<id>.jpg 로 저장
  python3 update.py undo --book '폭풍이 온다'     # 그 책의 마지막 기록 삭제
  python3 update.py list                           # 현재 상태 보기
공통 옵션: --no-push (커밋만), --dry-run (파일 저장/커밋 안 함)
--book 은 제목(정확히 또는 고유한 일부) 또는 id.
"""
import argparse, json, os, subprocess, sys, time, re, shutil, urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data.json')
STATUS = {'plan': '읽을 예정', 'reading': '읽는 중', 'done': '완독', 'stop': '중단'}
STATUS_ALIAS = {'읽을예정': 'plan', '읽을 예정': 'plan', '읽는중': 'reading', '읽는 중': 'reading',
                '완독': 'done', '중단': 'stop', **{k: k for k in STATUS}}
AUTHOR = ('SuddenlySlowly', 'SuddenlySlowly@users.noreply.github.com')


def now_kst(): return datetime.now(KST)
def today(): return now_kst().strftime('%Y-%m-%d')
def die(msg): print('오류:', msg, file=sys.stderr); sys.exit(1)


def valid_date(s):
    try: datetime.strptime(s, '%Y-%m-%d'); return s
    except ValueError: raise argparse.ArgumentTypeError('날짜는 YYYY-MM-DD 형식이어야 해요')


def load():
    with open(DATA, encoding='utf-8') as f: return json.load(f)


def save(d):
    d['updatedAt'] = now_kst().isoformat(timespec='seconds')
    with open(DATA, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2); f.write('\n')


def fetch_cover(src, book_id):
    """URL 또는 로컬 경로의 이미지를 covers/<id>.<ext> 로 저장하고 상대 경로를 반환."""
    if re.match(r'https?://', src):
        if shutil.which('curl'):  # 일부 이미지 서버는 파이썬 SSL과 호환이 안 돼서 curl 우선
            r = subprocess.run(['curl', '-sSfL', '--max-time', '30', '-A', 'Mozilla/5.0', src], capture_output=True)
            if r.returncode: die('표지 다운로드 실패: ' + r.stderr.decode(errors='ignore').strip())
            raw = r.stdout
        else:
            req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0 (reading-tracker)'})
            with urllib.request.urlopen(req, timeout=30) as r: raw = r.read()
    else:
        if not os.path.isfile(src): die(f'표지 파일이 없어요: {src}')
        with open(src, 'rb') as f: raw = f.read()
    if raw[:3] == b'\xff\xd8\xff': ext = 'jpg'
    elif raw[:8] == b'\x89PNG\r\n\x1a\n': ext = 'png'
    elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP': ext = 'webp'
    elif raw[:6] in (b'GIF87a', b'GIF89a'): ext = 'gif'
    else: die('이미지 파일이 아니에요 (jpg/png/webp/gif만 가능)')
    os.makedirs(os.path.join(HERE, 'covers'), exist_ok=True)
    for old in os.listdir(os.path.join(HERE, 'covers')):
        if os.path.splitext(old)[0] == book_id: os.remove(os.path.join(HERE, 'covers', old))
    rel = f'covers/{book_id}.{ext}'
    with open(os.path.join(HERE, rel), 'wb') as f: f.write(raw)
    print(f'표지 저장: {rel} ({len(raw) // 1024}KB)')
    return rel


def find_book(d, key):
    for b in d['books']:
        if b['id'] == key or b['title'] == key: return b
    norm = lambda s: re.sub(r'\s+', '', s).lower()
    hits = [b for b in d['books'] if norm(key) in norm(b['title'])]
    if len(hits) == 1: return hits[0]
    if not hits: die(f"'{key}' 책을 찾을 수 없어요. 등록된 책: " + ', '.join(b['title'] for b in d['books']))
    die(f"'{key}'에 해당하는 책이 여러 권이에요: " + ', '.join(b['title'] for b in hits))


def cur_page(d, b):
    p = max([l['to'] for l in d['logs'] if l['bookId'] == b['id']] or [0])
    if b.get('totalPages') and b.get('status') == 'done': p = max(p, b['totalPages'])
    return p


def auto_done(d, b, date):
    """총 페이지에 도달하면 완독 처리. 메시지 반환."""
    t = b.get('totalPages')
    if t and cur_page(d, b) >= t and b.get('status') != 'done':
        b['status'] = 'done'; b['endDate'] = b.get('endDate') or date
        return f"🎉 '{b['title']}' 완독 처리 (완독일 {b['endDate']})"
    return ''


def summary(d, b):
    p, t = cur_page(d, b), b.get('totalPages')
    prog = f"{p}/{t}쪽 ({round(p / t * 100)}%)" if t else f"{p}쪽 읽음 · 총 페이지 미입력"
    return f"[{b['id']}] {b['title']} — {STATUS[b['status']]} — {prog}"


def git_commit_push(msg, push=True):
    def run(*a): return subprocess.run(a, cwd=HERE, check=True, capture_output=True, text=True)
    run('git', 'add', '-A', 'data.json', 'covers') if os.path.isdir(os.path.join(HERE, 'covers')) else run('git', 'add', 'data.json')
    if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=HERE).returncode == 0:
        print('변경 사항 없음'); return
    run('git', '-c', f'user.name={AUTHOR[0]}', '-c', f'user.email={AUTHOR[1]}', 'commit', '-m', msg)
    print('커밋:', msg)
    if push:
        r = subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=HERE, capture_output=True, text=True)
        if r.returncode: die('push 실패:\n' + r.stderr)
        print('push 완료 → https://suddenlyslowly.github.io/reading-tracker/ (반영까지 1~2분)')


def main():
    ap = argparse.ArgumentParser(description='독서 기록 data.json 업데이트')
    ap.add_argument('--no-push', action='store_true'); ap.add_argument('--dry-run', action='store_true')
    sp = ap.add_subparsers(dest='cmd', required=True)
    g = sp.add_parser('log', help='진척도 기록')
    g.add_argument('--book', required=True); g.add_argument('--page', type=int, required=True, help='도달한(끝) 페이지')
    g.add_argument('--from', dest='frm', type=int, help='범위 기록 시 시작 페이지')
    g.add_argument('--date', type=valid_date); g.add_argument('--note', default='')
    a = sp.add_parser('add-book', help='책 추가')
    a.add_argument('--title', required=True); a.add_argument('--author', default='')
    a.add_argument('--pages', type=int); a.add_argument('--status', default='reading')
    a.add_argument('--start', type=valid_date); a.add_argument('--memo', default=''); a.add_argument('--cover', help='표지 이미지 URL 또는 파일 경로')
    s = sp.add_parser('set', help='책 정보 수정')
    s.add_argument('--book', required=True); s.add_argument('--title'); s.add_argument('--author')
    s.add_argument('--pages', type=int); s.add_argument('--status'); s.add_argument('--rating', type=int)
    s.add_argument('--start', type=valid_date); s.add_argument('--end', type=valid_date); s.add_argument('--memo')
    s.add_argument('--cover', help='표지 이미지 URL 또는 파일 경로 ("" = 표지 제거)')
    u = sp.add_parser('undo', help='책의 마지막 기록 삭제'); u.add_argument('--book', required=True)
    sp.add_parser('list', help='현재 상태 보기')
    for p in (g, a, s, u):  # 하위 명령 뒤에도 공통 옵션 허용
        p.add_argument('--no-push', action='store_true', default=argparse.SUPPRESS)
        p.add_argument('--dry-run', action='store_true', default=argparse.SUPPRESS)
    args = ap.parse_args()
    d = load()

    if args.cmd == 'list':
        print('마지막 업데이트:', d.get('updatedAt'))
        for b in d['books']: print(summary(d, b))
        return

    msgs = []
    if args.cmd == 'log':
        b = find_book(d, args.book); date = args.date or today(); t = b.get('totalPages')
        if args.page < 1: die('페이지는 1 이상이어야 해요')
        if t and args.page > t: die(f"총 페이지({t}쪽)보다 클 수 없어요")
        if args.frm is not None and not (0 <= args.frm <= args.page): die('범위를 확인해 주세요 (--from ≤ --page)')
        prev = cur_page(d, b)
        d['logs'].append({'id': 'l' + format(int(time.time() * 1000), 'x'), 'created': int(time.time() * 1000), 'date': date,
                          'bookId': b['id'], 'mode': 'range' if args.frm is not None else 'reach',
                          'from': args.frm, 'to': args.page, 'note': args.note})
        if b['status'] in ('plan', 'stop'): b['status'] = 'reading'; msgs.append("상태 → 읽는 중")
        if not b.get('startDate'): b['startDate'] = date
        if args.frm is None and args.page < prev: msgs.append(f"⚠ 이전 기록({prev}쪽)보다 작은 페이지예요")
        m = auto_done(d, b, date); m and msgs.append(m)
        commit = f"기록: {b['title']} {args.page}쪽 ({date})"
    elif args.cmd == 'add-book':
        st = STATUS_ALIAS.get(args.status) or die('상태는 plan/reading/done/stop 중 하나')
        if any(x['title'] == args.title for x in d['books']): die('이미 같은 제목의 책이 있어요')
        n = 1 + max([int(x['id'][1:]) for x in d['books'] if re.fullmatch(r'b\d+', x['id'])] or [0])
        b = {'id': f'b{n}', 'title': args.title, 'author': args.author, 'totalPages': args.pages, 'status': st,
             'startDate': args.start or (today() if st == 'reading' else ''), 'endDate': today() if st == 'done' else '',
             'rating': None, 'memo': args.memo, 'created': int(time.time() * 1000)}
        if args.cover and not args.dry_run: b['cover'] = fetch_cover(args.cover, b['id'])
        d['books'].append(b); commit = f"책 추가: {b['title']}"
    elif args.cmd == 'set':
        b = find_book(d, args.book)
        for k, attr in (('title', 'title'), ('author', 'author'), ('pages', 'totalPages'), ('start', 'startDate'), ('end', 'endDate'), ('memo', 'memo')):
            v = getattr(args, k)
            if v is not None: b[attr] = (v if v > 0 else None) if k == 'pages' else v
        if args.cover is not None and not args.dry_run:
            if args.cover == '':
                b.pop('cover', None)
                for old in (os.listdir(os.path.join(HERE, 'covers')) if os.path.isdir(os.path.join(HERE, 'covers')) else []):
                    if os.path.splitext(old)[0] == b['id']: os.remove(os.path.join(HERE, 'covers', old))
            else: b['cover'] = fetch_cover(args.cover, b['id'])
        if args.rating is not None:
            if not 0 <= args.rating <= 5: die('별점은 1~5 (0은 지우기)')
            b['rating'] = args.rating or None
        if args.status:
            b['status'] = STATUS_ALIAS.get(args.status) or die('상태는 plan/reading/done/stop 중 하나')
            if b['status'] == 'done' and not b.get('endDate'): b['endDate'] = today()
        if b.get('totalPages') and cur_page(d, b) > b['totalPages']:
            msgs.append(f"⚠ 기록된 페이지({cur_page(d, b)}쪽)가 총 페이지보다 커요")
        m = auto_done(d, b, today()); m and msgs.append(m)
        commit = f"수정: {b['title']}"
    elif args.cmd == 'undo':
        b = find_book(d, args.book)
        mine = [l for l in d['logs'] if l['bookId'] == b['id']]
        if not mine: die('삭제할 기록이 없어요')
        last = max(mine, key=lambda l: (l['date'], l.get('created', 0)))
        d['logs'].remove(last); commit = f"기록 취소: {b['title']} {last['to']}쪽 ({last['date']})"

    for m in msgs: print(m)
    print(summary(d, b))
    if args.dry_run: print('(dry-run: 저장하지 않음)'); return
    save(d)
    git_commit_push(commit, push=not args.no_push)


if __name__ == '__main__':
    main()
