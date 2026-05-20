/**
 * api.js — Financial Pulse API 연동 공통 모듈
 *
 * 모든 fetch 요청은 이 파일의 함수를 통해 처리합니다.
 * 응답 구조: { success, message, data }
 */

const BASE_URL = 'http://127.0.0.1:8000';   // ← 서버 주소 여기서만 관리
//const BASE_URL= "https://extensions-kingdom-calling-tablets.trycloudflare.com";
// ================================================================
// 공통 fetch 함수
// ================================================================
async function api(method, path, body = null) {
    const opts = {
        method,
        headers  : { 'Content-Type': 'application/json' },
        credentials: 'include',   // 세션 쿠키 자동 포함
    };
    if (body) opts.body = JSON.stringify(body);

    const res  = await fetch(BASE_URL + path, opts);
    const data = await res.json();

    // 서버 공통 응답 { success, message, data } 기준
    if (!data.success) throw new Error(data.message || '서버 오류가 발생했습니다.');
    return data;
}


// ================================================================
// 버튼 로딩 상태 유틸
// ================================================================
function setBtnLoading(btnEl, loading, originalText = null) {
    if (loading) {
        btnEl.disabled    = true;
        btnEl.dataset.orig = btnEl.innerText;
        btnEl.innerText   = '처리 중...';
    } else {
        btnEl.disabled  = false;
        btnEl.innerText = originalText || btnEl.dataset.orig || btnEl.innerText;
    }
}


// ================================================================
// [1] 로그인
// POST /membership/login
// ================================================================
async function apiLogin(email, password) {
    const res = await api('POST', '/membership/login', { email, password });
    sessionStorage.setItem('fp_uid',   res.data.u_id);
    sessionStorage.setItem('fp_email', email);        // ← 추가

    // core.js의 checkSession()이 fp_session을 보므로 함께 저장
    localStorage.setItem('fp_session', JSON.stringify({
    email: email,
    u_id : res.data.u_id,
    role : res.data.role || 'user',
    ts   : Date.now()
}));

    return res.data;
}


// ================================================================
// [2] 로그아웃
// POST /membership/logout
// ================================================================
async function apiLogout() {
    await api('POST', '/membership/logout');
    sessionStorage.removeItem('fp_uid');
    location.replace('login.html');
}


// ================================================================
// [3] 회원가입
// POST /membership/signup
// ================================================================
async function apiSignup(email, password, name, phone_num) {
    const res = await api('POST', '/membership/signup', { email, password, name, phone_num });
    return res.data;
}


// ================================================================
// [4] 이메일 중복 확인
// POST /membership/check-email
// ================================================================
async function apiCheckEmail(email) {
    try {
        await api('POST', '/membership/check-email', { email });
        return { available: true, message: '사용 가능한 이메일입니다.' };
    } catch (e) {
        return { available: false, message: e.message };
    }
}


// ================================================================
// [5] 아이디 찾기
// POST /membership/find-id
// ================================================================
async function apiFindId(name, phone_num) {
    const res = await api('POST', '/membership/find-id', { name, phone_num });
    return res.data.email;
}


// ================================================================
// [6] 비밀번호 찾기 (임시 비밀번호 발급)
// POST /membership/find-pw
// ================================================================
async function apiFindPw(email, name, phone_num) {
    await api('POST', '/membership/find-pw', { email, name, phone_num });
}

// ================================================================
// [7] 비밀번호 변경
// PUT /membership/change-pw
// ================================================================
async function apiChangePw(current_pw, new_pw, new_pw_check) {
    await api('PUT', '/membership/change-pw', { current_pw, new_pw, new_pw_check });
}


// ================================================================
// [8] 회원정보 변경 1단계 — 비밀번호 본인 확인
// POST /membership/verify-pw
// ================================================================
async function apiVerifyPw(password) {
    await api('POST', '/membership/verify-pw', { password });
}


// ================================================================
// [9] 회원정보 변경 2단계 — 이름/전화번호 수정
// PUT /membership/update-info
// ================================================================
async function apiUpdateInfo(name = null, phone_num = null) {
    const res = await api('PUT', '/membership/update-info', { name, phone_num });
    return res.data;
}


// ================================================================
// [10] 회원 탈퇴
// DELETE /membership/withdraw
// ================================================================
async function apiWithdraw() {
    await api('DELETE', '/membership/withdraw', { confirmed: true });
    sessionStorage.removeItem('fp_uid');
    location.replace('login.html');
}

// ================================================================
// 관리자 인증 확인
// GET /admin/me
// ================================================================
async function apiAdminMe() {
    const res = await api('GET', '/admin/me');
    return res.data;
}