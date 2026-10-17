# -*- coding: utf-8 -*-
"""
접근 통제 (호칭박스·매직박스 공통 입구)

- 사용자 명단은 Firebase(Firestore)의 `users` 모음에 둔다. 문서 ID = 일련번호.
    login_id   아이디
    salt, code_hash   접속 코드(평문은 저장하지 않음)
    active     True/False — 끄면 즉시 막힌다(앱을 다시 올릴 필요 없음)
    admin      True면 사용자 관리 화면을 볼 수 있다
    apps       쓸 수 있는 앱 목록(예: ["hobox","magicbox"]). 없으면 모든 앱.
    note       메모(이름·소속 등)
    last_login 마지막 접속 시각
- Streamlit Secrets 에 `firebase_json`(서비스 계정 JSON 파일 내용 통째로)과 `setup_key`(최초 관리자 만들 때만 씀)를 넣는다.
- 설정이 없으면 열리지 않는다(실수로 공개되는 것을 막기 위해). 로컬 시험은 환경변수 ACCESS_DEV=1.
"""
import hashlib
import hmac
import os
import secrets as pysecrets
import time
from datetime import datetime, timezone

import streamlit as st

COLLECTION = "users"
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"      # 헷갈리는 글자(0 o 1 l i) 제외
MAX_TRIES = 5


# ───────── 저장소 (Firestore / 시험용 메모리) ─────────
class MemoryStore:
    """시험용. 같은 인터페이스."""
    def __init__(self):
        self.d = {}

    def all(self):
        return {k: dict(v) for k, v in self.d.items()}

    def set(self, uid, data):
        self.d.setdefault(uid, {}).update(data)


class FirestoreStore:
    def __init__(self, info):
        from google.cloud import firestore
        from google.oauth2 import service_account
        cred = service_account.Credentials.from_service_account_info(dict(info))
        self.col = firestore.Client(project=info["project_id"], credentials=cred).collection(COLLECTION)

    def all(self):
        return {d.id: d.to_dict() for d in self.col.stream()}

    def set(self, uid, data):
        self.col.document(uid).set(data, merge=True)


@st.cache_resource
def get_store():
    info = None
    try:
        if "firebase_json" in st.secrets:       # 받은 JSON 파일 내용을 통째로 붙여 넣는 방식(권장)
            import json
            info = json.loads(st.secrets["firebase_json"])
        elif "firebase" in st.secrets:          # 항목별로 옮겨 적는 방식
            info = dict(st.secrets["firebase"])
    except Exception:           # secrets 파일이 없거나 내용이 잘못된 경우
        info = None
    if info:
        return FirestoreStore(info)
    if os.environ.get("ACCESS_DEV") == "1":
        return MemoryStore()
    return None


# ───────── 순수 로직 (화면과 무관, 시험 가능) ─────────
def hash_code(code, salt):
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()


def new_code(n=8):
    return "".join(pysecrets.choice(ALPHABET) for _ in range(n))


def make_secret(code):
    salt = pysecrets.token_hex(16)
    return {"salt": salt, "code_hash": hash_code(code, salt)}


def next_uid(users):
    nums = [int(k) for k in users if k.isdigit()]
    return str(max(nums) + 1 if nums else 1)


def add_user(store, login_id, note="", admin=False, apps=None, code=None):
    login_id = login_id.strip()
    users = store.all()
    if not login_id:
        raise ValueError("아이디를 입력하세요.")
    if any(u.get("login_id") == login_id for u in users.values()):
        raise ValueError("이미 있는 아이디입니다.")
    code = code or new_code()
    uid = next_uid(users)
    data = {"login_id": login_id, "active": True, "admin": bool(admin), "note": note, **make_secret(code)}
    if apps:
        data["apps"] = list(apps)
    store.set(uid, data)
    return uid, code


def reset_code(store, uid):
    code = new_code()
    store.set(uid, make_secret(code))
    return code


def authenticate(store, login_id, code, app):
    """-> (user dict | None, 메시지)"""
    users = store.all()
    hit = next(((k, u) for k, u in users.items() if u.get("login_id") == login_id.strip()), None)
    # 아이디가 없어도 같은 시간을 쓰도록 해시를 한 번 계산한다
    if hit is None:
        hash_code(code, "00" * 16)
        return None, "아이디 또는 접속 코드가 맞지 않습니다."
    uid, u = hit
    ok = hmac.compare_digest(hash_code(code, u["salt"]), u["code_hash"])
    if not ok:
        return None, "아이디 또는 접속 코드가 맞지 않습니다."
    if not u.get("active", False):
        return None, "사용이 중지된 계정입니다. 관리자에게 문의하세요."
    if u.get("apps") and app not in u["apps"]:
        return None, "이 앱을 쓸 권한이 없습니다."
    store.set(uid, {"last_login": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return {"uid": uid, **u}, ""


# ───────── 화면 ─────────
def _admin_panel(store, me):
    with st.sidebar.expander("사용자 관리 (관리자)"):
        users = store.all()
        rows = [{"번호": k, "아이디": u.get("login_id"), "사용": u.get("active", False), "관리자": u.get("admin", False),
                 "메모": u.get("note", ""), "앱": ",".join(u.get("apps", [])) or "전체", "마지막 접속": u.get("last_login", "")}
                for k, u in sorted(users.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)]
        st.dataframe(rows, hide_index=True)
        st.markdown("**새 사용자**")
        nid = st.text_input("아이디", key="adm_new_id")
        nnote = st.text_input("메모(이름·소속)", key="adm_new_note")
        if st.button("추가", key="adm_add"):
            try:
                uid, code = add_user(store, nid, nnote)
                st.success(f"{uid}번 {nid} 추가. 접속 코드: **{code}** (지금만 보입니다. 사용자에게 전달하세요.)")
            except ValueError as e:
                st.error(str(e))
        st.markdown("**사용 중지 / 재개 / 코드 재발급**")
        ids = [r["번호"] for r in rows]
        sel = st.selectbox("번호", ids, key="adm_sel") if ids else None
        if sel:
            u = users[sel]
            c1, c2 = st.columns(2)
            if c1.button("중지" if u.get("active") else "재개", key="adm_toggle"):
                if sel == me["uid"] and u.get("active"):
                    st.error("자기 자신은 중지할 수 없습니다.")
                else:
                    store.set(sel, {"active": not u.get("active", False)})
                    st.rerun()
            if c2.button("코드 재발급", key="adm_reset"):
                st.success(f"새 접속 코드: **{reset_code(store, sel)}** (지금만 보입니다.)")


def _bootstrap(store):
    st.title("최초 관리자 만들기")
    st.info("아직 사용자가 없습니다. Streamlit Secrets에 넣어 둔 설치 키(setup_key)와 함께 관리자 계정을 만드세요.")
    key = st.text_input("설치 키", type="password")
    lid = st.text_input("관리자 아이디")
    code = st.text_input("접속 코드 (8자 이상)", type="password")
    if st.button("만들기"):
        try:
            want = st.secrets.get("setup_key", None)
        except Exception:
            want = os.environ.get("ACCESS_SETUP_KEY")
        if not want or not hmac.compare_digest(key, str(want)):
            st.error("설치 키가 맞지 않습니다.")
        elif len(code) < 8:
            st.error("접속 코드는 8자 이상이어야 합니다.")
        else:
            try:
                add_user(store, lid, "최초 관리자", admin=True, code=code)
                st.success("만들었습니다. 새로고침 후 로그인하세요.")
            except ValueError as e:
                st.error(str(e))
    st.stop()


def require_access(app):
    """앱 맨 위에서 부른다. 통과하면 사용자 dict를 돌려주고, 아니면 화면을 멈춘다."""
    store = get_store()
    if store is None:
        st.error("접근 통제 설정(Firebase)이 없어 열 수 없습니다. 관리자에게 문의하세요.")
        st.stop()
    me = st.session_state.get("_user")
    if me and me.get("_app") == app:
        with st.sidebar:
            st.caption(f"로그인: {me['login_id']} ({me['uid']}번)")
            if st.button("로그아웃"):
                st.session_state.pop("_user", None)
                st.rerun()
        if me.get("admin"):
            _admin_panel(store, me)
        return me
    if not store.all():
        _bootstrap(store)
    st.title("로그인")
    if st.session_state.get("_tries", 0) >= MAX_TRIES:
        st.error("시도 횟수를 넘었습니다. 창을 닫고 잠시 후 다시 열어 주세요.")
        st.stop()
    with st.form("login"):
        lid = st.text_input("아이디")
        code = st.text_input("접속 코드", type="password")
        go = st.form_submit_button("들어가기")
    if go:
        u, msg = authenticate(store, lid, code, app)
        if u:
            u["_app"] = app
            st.session_state["_user"] = u
            st.session_state["_tries"] = 0
            st.rerun()
        st.session_state["_tries"] = st.session_state.get("_tries", 0) + 1
        time.sleep(1)
        st.error(msg)
    st.stop()
