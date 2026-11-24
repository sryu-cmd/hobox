# -*- coding: utf-8 -*-
"""호칭 망라 목록: 지정발언자 성명 '뒤'에 나온 호칭을 빠짐없이 모으고(인용문 문장 기준과 전체 기준을 나란히),
같은 직책의 다른 표기를 묶음 후보로 제안한다. 성명 '앞'에 나온 호칭은 인용문 호칭이 아니므로 따로 정리한다."""
import collections
import io
import re

import hobox_core as hc

PTOK = r'[가-힣0-9·]{1,14}(?:\([^)]{1,15}\))?'
BEFORE = re.compile(r'((?:' + PTOK + r'\s){0,3}' + PTOK + r')\s*$')
JUNK_END = re.compile(r'(에서|와|과|에|으로|로|한|난|된|관련|앞서|이에|반면|한편|나선|또|이어|그리고|하지만|다만|또한)$')
STOP = {'이에', '반면', '또', '그러나', '한편', '이어', '그리고', '이날', '오늘', '이', '그', '다만', '또한', '하지만'}
PARTY = {'더불어민주당', '민주당', '국민의힘', '국힘', '당', '야당', '여당', '캠프'}
ALIAS = {'더미래': '더좋은미래'}
ORGSUN = re.compile(r'(?:선거대책위원회|선대위원회|선대위|선대본부|선대본)')
TARGET = re.compile(r'(당대표|대표|최고위원|의원|시장|지사|대통령|총재|후보)$')


def _quote_near(text, s, e):
    return any(c in text[e:e + 80] for c in '“"') or any(c in text[max(0, s - 40):s] for c in '”"')


BADFIRST = {'등', '두', '세', '네', '양', '각', '총', '약'}


def _noisy(form):
    toks = form.split()
    if len(toks) > 4 or toks[0] in BADFIRST:
        return True
    if any(re.search(r'\d|명$', t) for t in toks):
        return True
    return any(re.search(r'(은|는|가|이|을|를|의|도|만|에서|까지|에|과|와)$', t) and t not in ('국회', '위원회') and not re.search(r'(위원회|회의)$', t) for t in toks[:-1])


def _clean_tokens(form):
    toks = [t for t in form.split() if t]
    while toks and (toks[0] in STOP or (JUNK_END.search(toks[0]) and len(toks) > 1)):
        toks = toks[1:]
    return toks


def _key(form):
    """-> (묶음 키, 지향 직책)"""
    toks = _clean_tokens(form)
    if not toks:
        return form, ''
    if toks[-1] == '후보' and len(toks) >= 1:
        prev = ' '.join(toks[:-1])
        tgt = toks[-2] if len(toks) >= 2 and TARGET.search(toks[-2]) else ''
        return '후보', tgt
    toks = [t for t in toks if t not in PARTY and '모임' not in t and t not in ('최대', '신임', '현')]
    s = ' '.join(ALIAS.get(t, t) for t in toks)
    s = ORGSUN.sub('', s).strip()
    compact = s.replace(' ', '')
    compact = re.sub(r'^대선', '', compact)
    compact = compact.replace('위원회', '위') if not compact.endswith('위원회') else compact
    return compact or form.replace(' ', ''), ''


def analyze_mangra(header, data, name):
    di, ti, tt, ui = hc._read_cols(header)
    seen, hitsA, hitsB = set(), [], []
    n_art = 0
    for r in data:
        r = r + [''] * (len(header) - len(r))
        u = r[ui] if ui is not None else ''
        if u and u in seen:
            continue
        seen.add(u)
        text, dt = r[ti], hc.norm_date(r[di])
        if not dt:
            continue
        dt = str(dt)
        if name not in text:
            continue
        n_art += 1
        url = u or r[tt]
        for c in hc.candidates(text, name):
            jeon, title, retro, ctx, s, e, josa = c
            toks = title.split()
            if toks and (toks[0] in STOP or any(hc.looks_like_name(t) for t in toks[:-1]) or _noisy(' '.join(_clean_tokens(title)) or title)):
                continue
            q = _quote_near(text, s, e) and (josa in hc.SUBJ or josa == '')
            hitsA.append((dt, ' '.join(_clean_tokens(title)) or title, bool(jeon), q, josa, url))
        for m in re.finditer(re.escape(name) + r'(?![가-힣])', text):
            before = text[max(0, m.start() - 40):m.start()].rstrip()
            mm = BEFORE.search(before)
            if not mm:
                continue
            toks = mm.group(1).split()
            last = re.sub(r'\([^)]*\)', '', toks[-1])
            if not hc.TITLE_SUFFIX.search(last):
                last = re.sub(r'(인데|이자|인|로서|으로|로)$', '', last)
            if not (hc.TITLE_SUFFIX.search(last) and len(last) >= 2):
                continue
            tk, j = [last], len(toks) - 1
            while j > 0 and len(tk) < 4:
                p = re.sub(r'\([^)]*\)', '', toks[j - 1])
                if p[-1:] in '은는이가도을를의,' or hc.TITLE_SUFFIX.search(p):
                    break
                tk.insert(0, p)
                j -= 1
            if any(hc.looks_like_name(t) for t in tk[:-1]) or _noisy(' '.join(tk)):
                continue
            hitsB.append((dt, ' '.join(_clean_tokens(' '.join(tk)) or tk), url))
    return _build(name, n_art, hitsA, hitsB)


def _agg(rows, keyf):
    by = collections.defaultdict(list)
    for h in rows:
        by[keyf(h)].append(h)
    return by


def _build(name, n_art, hitsA, hitsB):
    T = ['묶음(제안)', '묶음(수정)', '앞에 붙은 구분', '지향 직책(후보)', '추정 정식 호칭(약칭일 때)',
         '인용문 문장 기사수', '인용문 기준 첫 등장', '인용문 기준 마지막 등장', '전체 기사수', '전체 기준 첫 등장', '전체 기준 마지막 등장',
         '표기 변형(전체 건수/인용문 건수)', '주로 쓰인 조사', '인용문 첫 근거 기사', '인용문 마지막 근거 기사']
    keyed = []
    for dt, form, jeon, q, josa, url in hitsA:
        k, tgt = _key(form)
        keyed.append((dt, form, jeon, q, josa, url, ('전 ' if jeon else '') + k, tgt))
    # 묶음 대표 표기: 가장 많이 쓰인 표기
    by = _agg(keyed, lambda h: h[6])
    full_forms = {k: g for k, g in by.items()}
    rows = []
    for k, g in by.items():
        q = sorted([h for h in g if h[3]], key=lambda h: h[0])
        var = collections.Counter()
        varq = collections.Counter()
        for h in g:
            var[h[1]] += 0
        arts = collections.defaultdict(set)
        artsq = collections.defaultdict(set)
        for h in g:
            arts[h[1]].add(h[5])
            if h[3]:
                artsq[h[1]].add(h[5])
        vs = sorted(arts, key=lambda f: -len(arts[f]))
        label = vs[0] if vs else k
        disp = _label(k, vs, arts)
        tg = collections.Counter(h[7] for h in g if h[7]).most_common(1)
        hint = ''
        if k.lstrip('전 ') in ('단장', '기획단장', '공동단장') or (len(k) <= 4 and k.endswith('단장') and k != '대선기획단장'):
            nearby = collections.Counter()
            for h in g:
                for o in keyed:
                    if o[6] != k and o[6].endswith(k.lstrip('전 ')) and len(o[6]) > len(k) and abs(_days(o[0]) - _days(h[0])) <= 14:
                        nearby[o[6]] += 1
            hint = ', '.join(a for a, n in nearby.most_common(2))
        rows.append([disp, disp, '전직' if k.startswith('전 ') else '', tg[0][0] if tg else '', hint,
                     len({h[5] for h in q}), q[0][0] if q else '', q[-1][0] if q else '',
                     len({h[5] for h in g}), min(h[0] for h in g), max(h[0] for h in g),
                     '; '.join(f"{f}({len(arts[f])}/{len(artsq[f])})" for f in vs),
                     ', '.join(f"{j or '없음'}({c})" for j, c in collections.Counter(h[4] for h in g).most_common(3)),
                     q[0][5] if q else '', q[-1][5] if q else ''])
    rows.sort(key=lambda r: (-r[5], -r[8]))
    DT = ['묶음(제안)', '표기', '전체 기사수', '인용문 문장 기사수', '첫 등장', '마지막 등장']
    det = []
    for k, g in by.items():
        for f in {h[1] for h in g}:
            gg = [h for h in g if h[1] == f]
            det.append([k, f, len({h[5] for h in gg}), len({h[5] for h in gg if h[3]}), min(h[0] for h in gg), max(h[0] for h in gg)])
    det.sort(key=lambda r: (r[0], -r[2]))
    lab = {r[0]: None for r in rows}
    PT = ['묶음(제안)', '기사수', '첫 등장', '마지막 등장', '표기 변형(건수)', '비고']
    byb = _agg([(dt, _key(f)[0], f, url) for dt, f, url in hitsB], lambda h: h[1])
    pre = []
    for k, g in byb.items():
        c = collections.Counter(h[2] for h in g)
        pre.append([_label(k, sorted(c, key=lambda f: -c[f]), {f: set(range(c[f])) for f in c}), len({h[3] for h in g}), min(h[0] for h in g), max(h[0] for h in g),
                    '; '.join(f'{f}({n})' for f, n in c.most_common()), '이름 앞에 쓰인 호칭: 인용문 호칭으로 쓰지 않음'])
    pre.sort(key=lambda r: -r[1])
    return {'name': name, 'articles': n_art, 'T': T, 'rows': rows, 'DT': DT, 'det': det, 'PT': PT, 'pre': pre}


def _label(k, vs, arts):
    if k in ('후보', '전 후보'):
        return k
    best = max(vs, key=lambda f: (len(arts[f]), -len(f))) if vs else k
    toks = [t for t in _clean_tokens(best) if t not in PARTY and '모임' not in t and t not in ('최대', '신임', '현')]
    out = ' '.join(ALIAS.get(t, t) for t in toks) or best
    out = ORGSUN.sub('', out).strip() or out
    return ('전 ' if k.startswith('전 ') else '') + out


def _days(d):
    import datetime
    y, m, dd = d.split('-')
    return datetime.date(int(y), int(m), int(dd)).toordinal()


def mangra_xlsx(res):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    sheets = [('1.이름 뒤 호칭(묶음)', res['T'], res['rows'], (24, 24, 8, 12, 24, 10, 13, 13, 9, 13, 13, 70, 18, 40, 40)),
              ('2.표기별 상세', res['DT'], res['det'], (26, 30, 10, 12, 13, 13)),
              ('3.이름 앞 호칭(인용문 아님)', res['PT'], res['pre'], (26, 8, 13, 13, 70, 40))]
    for i, (title, hdr, rows, widths) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append(hdr)
        for r in rows:
            ws.append(r)
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = 'A2'
        for j, w in enumerate(widths):
            ws.column_dimensions[chr(65 + j)].width = w
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
