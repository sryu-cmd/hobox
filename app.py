# -*- coding: utf-8 -*-
"""
호칭박스 — 기사 전문에서 지정발언자의 '호칭별 기간'을 찾는다.

입력자료(발언문단/발언문장)를 만들 때, 기사 날짜에 맞지 않는 호칭을 쓰지 않도록
미리 호칭과 그 사용 기간을 파악하는 데 쓴다.

배포 방법: 매직박스와 같다 (Streamlit Cloud 등).  로컬 테스트: streamlit run app.py
"""
import os
import time
import pandas as pd
import streamlit as st
import hobox_core as hc

st.set_page_config(page_title="호칭박스", layout="wide")
HERE = os.path.dirname(os.path.abspath(__file__))


@st.cache_data
def default_seed():
    with open(os.path.join(HERE, "default_titles.csv"), encoding="utf-8-sig") as f:
        return f.read()


def merge_files(files):
    """업로드된 여러 파일을 열 이름 기준으로 합친다(URL이 같은 기사는 한 번만)."""
    header, rows, seen, msgs = None, [], set(), []
    for f in files:
        try:
            h, data = hc.read_table(f.getvalue(), f.name)
            hc._read_cols(h)
        except Exception as e:
            msgs.append(f"{f.name}: 읽지 못했습니다 ({e}). 날짜·전문·제목 열이 있는지 확인하세요.")
            continue
        if header is None:
            header = h
        idx = {n: i for i, n in enumerate(h)}
        for r in data:
            r = r + [""] * (len(h) - len(r))
            row = [r[idx[n]] if n in idx else "" for n in header]
            if "URL" in header:
                u = row[header.index("URL")]
                if u and u in seen:
                    continue
                seen.add(u)
            rows.append(row)
        msgs.append(f"{f.name}: {len(data):,}건")
    return header, rows, msgs


def to_df(header, rows):
    return pd.DataFrame(rows, columns=header)


st.title("호칭박스")
st.caption("기사 전문에서 지정발언자의 호칭별 사용 기간을 찾습니다. "
           "근거는 [이름+호칭]이 말하는 사람으로 쓰이고, 같은 문장에 큰따옴표 인용이 있는 경우만 씁니다.")

# ── 입력 ──
with st.sidebar:
    st.header("1. 입력")
    files = st.file_uploader("기사 전문 파일 (csv/xlsx, 여러 개 가능)", type=["csv", "xlsx"], accept_multiple_files=True)
    name = st.text_input("지정발언자 성명(풀네임)", placeholder="예: 고민정")
    minart = st.number_input("호칭별 최소 기사 수", min_value=1, max_value=20, value=3,
                             help="이보다 적게 나온 호칭은 표에서 뺍니다.")
    gap = st.number_input("외톨이 1건 판정 일수", min_value=7, max_value=365, value=60,
                          help="같은 호칭의 다른 날짜와 이 일수보다 더 떨어진 1건은 배제합니다. ('전 ○○'는 3배)")
    with st.expander("예시 호칭 리스트 (고쳐 쓸 수 있음)"):
        st.caption("1열=호칭, 3열=변형(쉼표로 구분). '전 의원, 전 대표…' 줄은 참고용입니다. "
                   "아래 칸을 직접 고치거나, 같은 형식의 CSV를 올리세요.")
        up = st.file_uploader("예시 리스트 CSV", type=["csv"], key="seed_up")
        seed_default = up.getvalue().decode("utf-8-sig") if up else default_seed()
        seed_text = st.text_area("예시 리스트", value=seed_default, height=300, key=f"seed_{bool(up)}")
    run = st.button("분석 시작", type="primary", disabled=not (files and name.strip()))

if run:
    header, rows, msgs = merge_files(files)
    if header is None:
        st.error("읽을 수 있는 파일이 없습니다.\n\n" + "\n".join(msgs))
        st.stop()
    t0 = time.time()
    with st.spinner("분석 중입니다…"):
        res = hc.analyze(header, rows, name.strip(), seed_text, minart=int(minart), isolated_gap=int(gap))
    if "error" in res:
        st.error(res["error"])
        st.stop()
    st.session_state.update(res=res, header=header, rows=rows, msgs=msgs, name=name.strip(), seed=seed_text,
                            minart=int(minart), gap=int(gap), final=None, secs=time.time() - t0)

res = st.session_state.get("res")
if not res:
    st.info("왼쪽에서 기사 전문 파일과 성명을 입력하고 [분석 시작]을 누르세요.")
    st.markdown("""
**사용 순서**
1. 기사 전문 파일을 올리고 성명을 입력합니다. (열 이름: 날짜 또는 일자, 전문 또는 본문, 제목, URL)
2. **1단계**: 예시 리스트에 있는 호칭의 시작일·종료일을 봅니다. 현직과 '전(前)'은 따로 나옵니다.
3. **2단계**: 예시에 없는데 기사에서 찾은 호칭 후보를 보고, 쓸 것에 체크합니다.
4. **3단계**: [선택한 호칭 반영]을 누르면 채택한 호칭까지 넣어 다시 계산합니다.
5. 엑셀로 내려받습니다.
""")
    st.stop()

s = res["stats"]
st.success(f"{res['name']} 언급 기사 {s['mentions']:,}건 ({s['first']} ~ {s['last']}) · "
           f"호칭이 잡힌 {s['caught']:,}건 중 인용문 문장 {s['used']:,}건을 근거로 썼습니다. "
           f"({st.session_state['secs']:.0f}초)")
with st.expander("읽은 파일"):
    st.write("\n".join(st.session_state["msgs"]))

# ── 1단계 ──
st.header("1단계. 예시 호칭의 기간")
st.caption("시작일·종료일은 그 호칭이 인용문 문장에 처음·마지막으로 나온 날짜입니다. 호칭이 실제로 시작·종료된 날과는 며칠 어긋날 수 있습니다.")
df1 = pd.DataFrame(res["t1"], columns=res["T1"])
st.dataframe(df1, width="stretch", hide_index=True)
if res["t3"]:
    with st.expander(f"배제된 외톨이 1건 ({len(res['t3'])}건)"):
        st.dataframe(pd.DataFrame(res["t3"], columns=res["T3"]), width="stretch", hide_index=True)

# ── 2단계 ──
st.header("2단계. 예시에 없는 호칭 후보")
if not res["t2"]:
    st.write("예시에 없는 호칭 후보가 없습니다.")
    adopted = []
else:
    st.caption("쓸 호칭에 체크하세요. '비정치 직종'으로 표시된 것은 동명이인이거나 경력 소개일 수 있습니다.")
    df2 = pd.DataFrame(res["t2"], columns=res["T2"])
    df2["선정(O/X)"] = False
    edited = st.data_editor(df2, width="stretch", hide_index=True,
                            disabled=[c for c in df2.columns if c != "선정(O/X)"], key="cand_editor",
                            column_config={"선정(O/X)": st.column_config.CheckboxColumn("선정", default=False)})
    adopted = edited.loc[edited["선정(O/X)"], "호칭"].tolist()
    if st.button("선택한 호칭 반영하여 다시 계산", disabled=not adopted):
        with st.spinner("다시 계산 중입니다…"):
            st.session_state["final"] = hc.analyze(st.session_state["header"], st.session_state["rows"],
                                                   st.session_state["name"], st.session_state["seed"],
                                                   minart=st.session_state["minart"], adopted=adopted,
                                                   isolated_gap=st.session_state["gap"])
            st.session_state["adopted"] = adopted

# ── 3단계 ──
final = st.session_state.get("final")
shown = final or res
if final:
    st.header("3단계. 채택한 호칭을 반영한 결과")
    st.caption("채택: " + ", ".join(st.session_state.get("adopted", [])))
    st.dataframe(pd.DataFrame(final["t1"], columns=final["T1"]), width="stretch", hide_index=True)

st.download_button("엑셀로 내려받기", data=hc.build_xlsx(shown),
                   file_name=f"호칭별_기간_{res['name']}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
