"""두 스냅샷 폴더를 비교해서 바뀐 화면과 바뀐 줄만 출력한다.

    python tools/compare_snapshots.py tools/snapshots/before tools/snapshots/after
    python tools/compare_snapshots.py tools/snapshots/before tools/snapshots/after --ignore-comments

들여쓰기·줄바꿈 같은 공백 차이는 무시한다. --ignore-comments를 주면 설명용 HTML 주석도 무시한다
(IE 조건부 주석 <!--[if ...]> 은 실제 동작이 있으므로 계속 비교한다).
"""
import argparse
import difflib
import os
import re
import sys


def tokens(path, ignore_comments):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    if ignore_comments:
        text = re.sub(r'<!--(?!\[if).*?-->', '', text, flags=re.S)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'>\s*<', '>\n<', text)  # 태그 단위로 한 줄씩
    return [t.strip() for t in text.split('\n') if t.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('before')
    parser.add_argument('after')
    parser.add_argument('--ignore-comments', action='store_true', help='설명용 HTML 주석 차이 무시')
    args = parser.parse_args()

    names = sorted(set(os.listdir(args.before)) | set(os.listdir(args.after)))
    same = 0
    for name in names:
        a, b = os.path.join(args.before, name), os.path.join(args.after, name)
        if not (os.path.exists(a) and os.path.exists(b)):
            print(f'== 한쪽에만 있음: {name}')
            continue
        ta, tb = tokens(a, args.ignore_comments), tokens(b, args.ignore_comments)
        if ta == tb:
            same += 1
            continue
        print(f'== 바뀜: {name}')
        for line in difflib.unified_diff(ta, tb, lineterm='', n=0):
            if not line.startswith(('---', '+++', '@@')):
                print('   ', line[:200])
    print(f'{same}/{len(names)}개 화면이 같습니다')
    return 0 if same == len(names) else 1


if __name__ == '__main__':
    sys.exit(main())
