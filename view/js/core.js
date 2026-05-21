// ========== 인증 모드 설정 ==========
const AUTH_MODE_DEV = false;

// ========== 더미 유저 ==========
function getDummyUser() {
  return { email: 'demo@finance.com', name: '데모사용자' };
}

// ========== 인증 체크 ==========
async function checkSession(adminOnly) {
  // 1. 로컬 스토리지/세션 스토리지에서 세션 확인
  let session = null;
  const sessionData = localStorage.getItem('fp_session') || sessionStorage.getItem('fp_session');
  if (sessionData) {
    try {
      session = JSON.parse(sessionData);
      const now = Date.now();
      if (session.ts && (now - session.ts) > 60 * 60 * 1000) {
        session = null;
        localStorage.removeItem('fp_session');
        sessionStorage.removeItem('fp_session');
      }
    } catch(e) { session = null; }
  }

  // 2. 개발 모드
  if (AUTH_MODE_DEV) {
    // 관리자 페이지: 세션이 없으면 자동으로 생성
    if (adminOnly) {
      if (session && session.email === 'admin@financepulse.com') {
        return session;
      } else {
        // 🔽 자동으로 관리자 세션 생성 (로그인 우회)
        console.log('개발 모드: 관리자 세션 자동 생성');
        const tempSession = { email: 'admin@financepulse.com', ts: Date.now() };
        localStorage.setItem('fp_session', JSON.stringify(tempSession));
        return tempSession;
      }
    } else {
      // 일반 페이지: 세션 있으면 그대로, 없으면 더미 유저
      return session ? session : getDummyUser();
    }
  }

  // 3. 운영 모드
  if (!session) {
    location.replace('login.html');
    return null;
  }
  if (adminOnly && session.role !== 'admin') {
    location.replace('login.html');
    return null;
  }
  return session;
}

async function doLogout() {
  try {
    await fetch(BASE_URL + '/membership/logout', {
      method     : 'POST',
      credentials: 'include',
    });
  } catch(e) {
    console.warn('logout API 오류:', e);
  }
  // sessionStorage 정리
  sessionStorage.removeItem('fp_session');
  sessionStorage.removeItem('fp_uid');
  sessionStorage.removeItem('fp_email');
  // localStorage 정리
  localStorage.removeItem('fp_session');
  localStorage.removeItem('fp_users');
  location.replace('login.html');
}

function renderSidebar(activeId) {
  let email = '';
  if (AUTH_MODE_DEV) {
    const sessionData = localStorage.getItem('fp_session') || sessionStorage.getItem('fp_session');
    if (sessionData) {
      try { email = JSON.parse(sessionData).email; } catch(e) { email = 'demo@finance.com'; }
    } else {
      email = 'demo@finance.com';
    }
  } else {
    const s = JSON.parse(localStorage.getItem('fp_session') || sessionStorage.getItem('fp_session') || 'null');
    email = s ? s.email : '';
  }

  // proto_v13 스타일의 사이드바 반환
  return `
    <aside class="sidebar">
      <div class="sb-logo">
        <img src="photo/LOGO.jpg" alt="Financial Pulse" onerror="this.parentElement.innerHTML='<div style=\'padding:20px;font-size:20px;font-weight:900;color:var(--navy)\'>Financial Pulse</div>'">
      </div>
      <div class="sb-nav">
        <a href="dashboard.html" class="nav-btn ${activeId === 'dashboard' ? 'active' : ''}"><i class="fas fa-chart-pie"></i> 메인 대시보드</a>
        <a href="keyword.html" class="nav-btn ${activeId === 'keyword' ? 'active' : ''}"><i class="fas fa-magnifying-glass-chart"></i> 키워드 트렌드</a>
        <a href="spike.html" class="nav-btn ${activeId === 'spike' ? 'active' : ''}"><i class="fas fa-fire-flame-curved"></i> 급등 기사 분석</a>
      </div>
      <div class="sb-profile" id="sbProfile">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:2px;">
          <div class="sp-label">현재 로그인</div>
          <div style="font-size:10px;font-weight:700;color:var(--teal);background:var(--teal-s);border:1px solid rgba(0,181,173,.2);border-radius:999px;padding:2px 8px;cursor:pointer;" id="mypageLabel">마이페이지</div>
        </div>
        <div class="sp-name" id="dashUserEmail">${email}</div>
        <button id="sidebarLogoutBtn" style="margin-top:12px;width:100%;background:rgba(231,76,60,.07);border:1.5px solid rgba(231,76,60,.18);border-radius:var(--rmd);padding:9px;color:var(--neg);font-weight:700;font-size:12px;cursor:pointer;font-family:inherit;transition:.2s;display:flex;align-items:center;justify-content:center;gap:7px;">
          <i class="fas fa-right-from-bracket"></i> 로그아웃
        </button>
      </div>
    </aside>
  `;
}

function makeSplitCol(sectors, lbl, ids, cc) {
  const ecoUrl = cc === 'kr' ? 'https://datacenter.hankyung.com/economic-calendar' : 'https://tradingeconomics.com/calendar';
  return `
    <div class="panel" style="padding:22px;">
      <div class="ph"><div class="pt">🔥 핫이슈 (${lbl})</div></div>
      <div id="${ids.hot}"></div>
    </div>
    <div class="panel trend-panel" style="padding:22px;">
      <div class="ph"><div class="pt">📈 오늘 섹터 성향 분석 (${lbl})</div></div>
      <div class="trend-list" id="${ids.trend}"></div>
    </div>
    <div class="panel sentiment-panel" style="padding:22px;">
      <div class="ph"><div class="pt">📊 성향 비율 (${lbl})</div></div>
      <div id="${ids.donut}" style="height:calc(100% - 50px);display:flex;align-items:center;justify-content:center;"></div>
    </div>
    <div class="panel" style="padding:22px;flex:1;display:flex;flex-direction:column;">
      <div class="ph"><div class="pt">📈 섹터별 긍/부정 비율</div></div>
      <div class="stack-list" id="${ids.stack}"></div>
    </div>
    <div class="panel" style="padding:22px;">
      <div class="ph"><div class="pt">📊 경제 지표</div><div class="pd" style="cursor:pointer;color:var(--teal);" id="${ids.eco}Title">상세보기 ↗</div></div>
      <div id="${ids.eco}" class="indicators-grid"></div>
    </div>
    <div class="panel" style="padding:22px;">
      <div class="ph"><div class="pt">📅 경제 일정</div><div class="pd"><a id="${ids.cal}Link" href="${ecoUrl}" target="_blank" style="color:var(--teal);font-weight:700;text-decoration:none;font-size:12px;">상세보기 ↗</a></div></div>
      <div id="${ids.cal}" class="sch-list"></div>
    </div>
  `;
}

// ========== (로컬스토리지 기반 테스트용) ==========
async function hashPw(p) {
  // 간단한 해시 (실제 운영에서는 SHA-256 권장, 테스트용)
  let hash = 0;
  for (let i = 0; i < p.length; i++) {
    hash = ((hash << 5) - hash) + p.charCodeAt(i);
    hash |= 0;
  }
  return hash.toString();
}

let users = [];
function loadUsers() {
  const s = localStorage.getItem('fp_users');
  if (s) users = JSON.parse(s);
  else users = [];
}
function saveUsers() {
  localStorage.setItem('fp_users', JSON.stringify(users));
}
function findByEmail(e) {
  return users.find(u => u.email === e);
}
function findByNamePhone(n, p) {
  return users.find(u => u.name === n && u.phone === p);
}
async function registerUser(email, pw, name, phone) {
  if (findByEmail(email)) throw new Error('이미 존재하는 이메일입니다.');
  if (pw.length < 6) throw new Error('비밀번호는 6자 이상이어야 합니다.');
  const h = await hashPw(pw);
  users.push({ email, passwordHash: h, name, phone, isTempPassword: false });
  saveUsers();
}
async function verifyLogin(email, pw) {
  const u = findByEmail(email);
  if (!u) return { success: false, message: '존재하지 않는 계정입니다.' };
  const h = await hashPw(pw);
  if (h !== u.passwordHash) return { success: false, message: '비밀번호가 일치하지 않습니다.' };
  if (u.isTempPassword) return { success: true, user: u, needChange: true };
  return { success: true, user: u, needChange: false };
}
async function issueTempPw(email) {
  const u = findByEmail(email);
  if (!u) throw new Error('등록된 이메일이 없습니다.');
  const tp = Math.random().toString(36).slice(2, 10) + Math.floor(1000 + Math.random() * 9000);
  const th = await hashPw(tp);
  u.passwordHash = th;
  u.isTempPassword = true;
  u.tempPlain = tp;
  saveUsers();
  return tp;
}
async function changePw(email, cur, nw) {
  const u = findByEmail(email);
  if (!u) throw new Error('사용자 없음');
  const ch = await hashPw(cur);
  if (ch !== u.passwordHash) throw new Error('현재 비밀번호가 일치하지 않습니다.');
  if (nw.length < 6) throw new Error('새 비밀번호는 6자 이상');
  const nh = await hashPw(nw);
  u.passwordHash = nh;
  u.isTempPassword = false;
  delete u.tempPlain;
  saveUsers();
}
function showDashboard(email) {
  // 대시보드 렌더링 로직 (필요시 구현, mypage에서는 미사용)
  console.log('showDashboard called for', email);
}

// 성향 분석 오버레이(공통)->키워드별 성향 data
const analysisData={
  "환율":{overall:{pos:65,neu:20,neg:15},sectors:[{name:"반도체",pos:70,neg:10},{name:"AI",pos:85,neg:5},{name:"자동차",pos:45,neg:35}]},
  "금리":{overall:{pos:58,neu:24,neg:18},sectors:[{name:"은행",pos:72,neg:12},{name:"부동산",pos:39,neg:41},{name:"채권",pos:68,neg:15}]},
  "반도체":{overall:{pos:74,neu:16,neg:10},sectors:[{name:"메모리",pos:82,neg:6},{name:"AI",pos:88,neg:4},{name:"장비",pos:66,neg:14}]},
  "AI":{overall:{pos:79,neu:13,neg:8},sectors:[{name:"반도체",pos:84,neg:5},{name:"클라우드",pos:77,neg:9},{name:"로봇",pos:71,neg:11}]},
  "AI & Tech":{overall:{pos:79,neu:13,neg:8},sectors:[{name:"반도체",pos:84,neg:5},{name:"클라우드",pos:77,neg:9},{name:"로봇",pos:71,neg:11}]},
  "테슬라":{overall:{pos:52,neu:18,neg:30},sectors:[{name:"전기차",pos:48,neg:38},{name:"배터리",pos:62,neg:22},{name:"자율주행",pos:45,neg:35}]},
  "2차전지":{overall:{pos:60,neu:22,neg:18},sectors:[{name:"양극재",pos:65,neg:15},{name:"전해질",pos:58,neg:20},{name:"분리막",pos:55,neg:25}]},
  "바이오":{overall:{pos:68,neu:20,neg:12},sectors:[{name:"신약",pos:72,neg:10},{name:"진단",pos:65,neg:15},{name:"의료기기",pos:67,neg:13}]},
  "자동차":{overall:{pos:55,neu:25,neg:20},sectors:[{name:"전기차",pos:60,neg:18},{name:"수소차",pos:52,neg:22},{name:"자율주행",pos:50,neg:28}]},
  "Inflation":{overall:{pos:35,neu:28,neg:37},sectors:[{name:"소비재",pos:30,neg:45},{name:"채권",pos:42,neg:32},{name:"부동산",pos:33,neg:40}]},
  "Big Tech":{overall:{pos:72,neu:15,neg:13},sectors:[{name:"클라우드",pos:78,neg:9},{name:"AI",pos:81,neg:7},{name:"광고",pos:57,neg:24}]},
  "Energy":{overall:{pos:63,neu:20,neg:17},sectors:[{name:"재생에너지",pos:74,neg:10},{name:"석유",pos:55,neg:28},{name:"가스",pos:60,neg:22}]},
  "Semiconductors":{overall:{pos:74,neu:16,neg:10},sectors:[{name:"메모리",pos:82,neg:6},{name:"AI칩",pos:88,neg:4},{name:"장비",pos:66,neg:14}]},
  "EV & Auto":{overall:{pos:58,neu:20,neg:22},sectors:[{name:"전기차",pos:60,neg:20},{name:"배터리",pos:64,neg:18},{name:"자율주행",pos:50,neg:28}]},
};
function _esc(s){if(!s)return'';return String(s).replace(/[&<>]/g,m=>m==='&'?'&amp;':m==='<'?'&lt;':'&gt;');}
function _genNews(kw,sectors){
  const pool=["시장 긴급 진단","전문가 전망 분석","투자 심리 변화","글로벌 이슈 영향","주요 지표 발표","상승 모멘텀","밸류에이션 분석","실적 전망","정책 수혜 기대","기관 리포트"];
  const srcs=["경제투데이","비즈니스워치","한국경제","연합뉴스","매일경제","파이낸셜뉴스","조선비즈","Bloomberg","Reuters","WSJ"];
  const news=[];
  for(let i=0;i<5;i++) news.push({title:`[${kw}] ${kw} ${pool[i]}`,source:srcs[i%srcs.length],sector:kw,tag:'긍정'});
  sectors.slice(0,5).forEach((s,i)=>news.push({title:`[${s.name}] ${s.name} 관련, ${pool[i+5]}`,source:srcs[(i+3)%srcs.length],sector:s.name,tag:s.pos>60?'긍정':s.neg>30?'부정':'중립'}));
  return news.slice(0,10);
}
function _drawDonut(container, overall){
  const {pos,neu,neg}=overall;
  const sz=250,r=sz/2,inn=65,cx=r;
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("width",sz);svg.setAttribute("height",sz);svg.setAttribute("viewBox",`0 0 ${sz} ${sz}`);
  let st=0;
  [[pos,'#2ECC71'],[neu,'#8E9CC5'],[neg,'#E74C3C']].forEach(([val,col])=>{
    if(val<=0)return;
    if(val>=100){
      const fc=document.createElementNS("http://www.w3.org/2000/svg","circle");
      fc.setAttribute("cx",cx);fc.setAttribute("cy",cx);
      fc.setAttribute("r",r);fc.setAttribute("fill",col);
      svg.appendChild(fc);st+=360;return;
    }
    const ang=(val/100)*360,end=st+ang;
    const rS=(st-90)*Math.PI/180,rE=(end-90)*Math.PI/180;
    const x1=cx+r*Math.cos(rS),y1=cx+r*Math.sin(rS),x2=cx+r*Math.cos(rE),y2=cx+r*Math.sin(rE);
    const lg=ang>180?1:0;
    const p=document.createElementNS("http://www.w3.org/2000/svg","path");
    p.setAttribute("d",`M ${cx} ${cx} L ${x1} ${y1} A ${r} ${r} 0 ${lg} 1 ${x2} ${y2} Z`);
    p.setAttribute("fill",col);p.setAttribute("stroke","#f0f6ff");p.setAttribute("stroke-width","3");
    svg.appendChild(p);st=end;
  });
  const ic=document.createElementNS("http://www.w3.org/2000/svg","circle");
  ic.setAttribute("cx",cx);ic.setAttribute("cy",cx);ic.setAttribute("r",inn);ic.setAttribute("fill","#f0f6ff");
  svg.appendChild(ic);
  container.innerHTML='';container.appendChild(svg);
}

// ================================================================
// API 기반 키워드 성향 분석 오버레이
// ================================================================
async function openAnalysisOverlay(kw) {
  if (!kw) return;
  const overlay = document.getElementById('analysisOverlay');
  const contentDiv = document.getElementById('aoContent');
  if (!overlay || !contentDiv) return;

  contentDiv.innerHTML = `
    <div style="display:flex;justify-content:center;align-items:center;min-height:300px;">
      <i class="fas fa-spinner fa-pulse" style="font-size:2rem;color:var(--teal);"></i>
      <span style="margin-left:12px;font-weight:600;">“${_esc(kw)}” 분석 중...</span>
    </div>
  `;
  overlay.classList.add('show');

  try {
    const url = `${BASE_URL}/api/search?keyword=${encodeURIComponent(kw)}`;
    console.log('[분석요청]', url);
    const res = await fetch(url, { credentials: 'include' });
    const json = await res.json();
    if (!json.success) throw new Error(json.message || '검색 결과 없음');

    const data = json.data;
    const overall = data.overall;
    const sectors = data.sectors || [];
    const articles = data.articles || [];

    let pos = overall.pos ?? 0;
    let neg = overall.neg ?? 0;
    let neu = Math.max(0, 100 - pos - neg);
    const score = (overall.score ?? (pos / 100)).toFixed(2);
    const scoreLabel = overall.label || (pos >= 60 ? '긍정' : pos <= 40 ? '부정' : '중립');
    const scoreCls = pos >= 60 ? 'var(--pos)' : pos <= 40 ? 'var(--neg)' : 'var(--neu)';

    // ★ dominant 계산
    const sentiments = [
      { label: '긍정', value: pos, color: '#2ECC71' },
      { label: '부정', value: neg, color: '#E74C3C' }
    ];
    const dominant = sentiments.reduce((max, s) => s.value > max.value ? s : max, sentiments[0]);

    contentDiv.innerHTML = `
      <div class="ao-kw-header">
        <div class="ao-kw-title"><div class="ao-acc-bar"></div><span>"${_esc(kw)}" 성향 분석 결과</span></div>
      </div>
      <div class="ao-main-grid">
        <div class="ao-card">
          <div class="ao-card-title"><i class="fas fa-circle-half-stroke"></i>전체 분위기 비율</div>
          <div class="ao-donut-wrap">
            <div class="ao-donut-chart-wrap">
              <div class="ao-donut-chart" id="aoMainDonut"></div>
              <div class="ao-donut-center">
                <strong>${dominant.value}%</strong>
                <small>${dominant.label}</small>
              </div>
            </div>
            <div class="ao-legend">
              <span class="ao-leg"><span class="ao-leg-dot" style="background:#2ECC71;"></span>긍정 ${pos}%</span>
              <span class="ao-leg"><span class="ao-leg-dot" style="background:#E74C3C;"></span>부정 ${neg}%</span>
            </div>
          </div>
          <div class="ao-score-box">
            <span class="ao-score-lbl">🎯 종합 성향 점수 (0~100)</span>
            <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
              <span class="ao-score-val">${score}</span>
              <span class="ao-score-badge" style="background:${pos>=60?'var(--pos-s)':pos<=40?'var(--neg-s)':'rgba(142,156,197,.12)'};color:${scoreCls};">${scoreLabel}</span>
            </div>
          </div>
          <div style="margin-top:7px;font-size:11px;color:var(--sub);">* 50 이상 긍정, 50 미만 부정 기준</div>
        </div>
        <div class="ao-card" style="display:flex;flex-direction:column;">
          <div class="ao-card-title"><i class="fas fa-chart-bar"></i>연관 분야별 긍정/부정 비교</div>
          <div class="ao-compare-grid" id="aoCompareGrid"></div>
          <div class="ao-cmp-legend">
            <span class="ao-leg"><span class="ao-leg-dot" style="background:#2ECC71;"></span>긍정 비율</span>
            <span class="ao-leg"><span class="ao-leg-dot" style="background:#E74C3C;"></span>부정 비율</span>
          </div>
          <div style="font-size:11px;color:var(--sub);margin-top:6px;">
            * 검색어가 포함된 기사들의 섹터별 긍/부정 비율
          </div>
        </div>
      </div>
      <div>
        <div class="ao-news-header">
          <div class="ao-card-title"><i class="fas fa-newspaper"></i>관련 뉴스 <span style="font-size:13px;color:var(--sub);">(클릭 시 원문 이동)</span></div>
          <div style="font-size:12px;color:var(--sub);">총 ${articles.length}개</div>
        </div>
        <div class="ao-news-grid" id="aoNewsList"></div>
      </div>
    `;

    _drawDonut(document.getElementById('aoMainDonut'), { pos, neu, neg });

    // 섹터 비교 (relevance 높은 순 3개)
    const topSectors = [...sectors].sort((a,b)=>(b.relevance||0)-(a.relevance||0)).slice(0,3);
    const compareGrid = document.getElementById('aoCompareGrid');
    compareGrid.innerHTML = '';
    topSectors.forEach(s => {
      const sPos = s.pos ?? 0;
      const sNeg = s.neg ?? 0;
      const ph = Math.min(sPos * 2.4, 210);
      const nh = Math.min(sNeg * 2.4, 210);
      const col = document.createElement('div');
      col.className = 'ao-cmp-col';
      col.innerHTML = `
        <div class="ao-bar-pair">
          <div class="ao-bw"><div class="ao-bv">${sPos}%</div><div class="ao-bar ao-bar-pos" style="height:${ph}px;"></div></div>
          <div class="ao-bw"><div class="ao-bv">${sNeg}%</div><div class="ao-bar ao-bar-neg" style="height:${nh}px;"></div></div>
        </div>
        <div class="ao-cmp-lbl">${_esc(s.sector)}</div>
      `;
      compareGrid.appendChild(col);
    });
    if (!topSectors.length) compareGrid.innerHTML = '<div style="padding:20px;text-align:center;">연관 분야 없음</div>';

    const newsContainer = document.getElementById('aoNewsList');
    newsContainer.innerHTML = '';
    articles.forEach(art => {
      const tendency = (art.tendency || '').toLowerCase();
      let tagClass = 'ao-tag-neu', tagText = '중립';
      if (tendency === 'positive') { tagClass = 'ao-tag-pos'; tagText = '긍정'; }
      else if (tendency === 'negative') { tagClass = 'ao-tag-neg'; tagText = '부정'; }
      const card = document.createElement('div');
      card.className = 'ao-news-card';
      card.style.cursor = 'pointer';
      card.innerHTML = `
        <div class="ao-news-title">📌 ${_esc(art.title)}</div>
        <div class="ao-news-meta">
          <span class="ao-nm-tag ${tagClass}">${tagText}</span>
          <span>📰 ${_esc(art.sector || '금융')}</span>
          <span>🏷️ 점수: ${(art.tend_score ?? art.score ?? 0).toFixed(1)}</span>
        </div>
      `;
      card.addEventListener('click', () => { if(art.url) window.open(art.url, '_blank'); });
      newsContainer.appendChild(card);
    });
  } catch (err) {
    console.error(err);
    contentDiv.innerHTML = `<div style="text-align:center;padding:40px;color:var(--neg);"><i class="fas fa-circle-exclamation"></i><br/>분석 실패: ${_esc(err.message)}</div>`;
  }
}
// --- Preview Image Logic ---
function showPreview(imgSrc) {
    const previewImg = document.getElementById('previewImage');
    const sparkline = document.getElementById('sparklineChart');
    if (previewImg && sparkline) {
        previewImg.src = imgSrc;
        previewImg.style.display = 'block';
        sparkline.style.display = 'none';
    }
}

const DOM_KW=[{keyword:"삼성전자",category:"산업",changeVal:5,changeType:"up",totalNews:224},{keyword:"네이버",category:"테크",changeVal:3,changeType:"up",totalNews:68},{keyword:"이재용",category:"인물",changeVal:2,changeType:"up",totalNews:112},{keyword:"반도체",category:"산업",changeVal:3,changeType:"up",totalNews:176},{keyword:"서울",category:"지역",changeVal:1,changeType:"up",totalNews:54},{keyword:"AI 규제",category:"정책",changeVal:-1,changeType:"down",totalNews:98},{keyword:"카카오",category:"테크",changeVal:0,changeType:"same",totalNews:61}];
const GBL_KW=[{keyword:"오픈AI",category:"테크",changeVal:4,changeType:"up",totalNews:198},{keyword:"엔비디아",category:"산업",changeVal:7,changeType:"up",totalNews:131},{keyword:"챗GPT",category:"테크",changeVal:3,changeType:"up",totalNews:312},{keyword:"미국",category:"지역",changeVal:2,changeType:"up",totalNews:145},{keyword:"젠슨 황",category:"인물",changeVal:3,changeType:"up",totalNews:108},{keyword:"구글",category:"테크",changeVal:2,changeType:"up",totalNews:187},{keyword:"실리콘밸리",category:"지역",changeVal:1,changeType:"up",totalNews:58}];

// 오늘의 키워드(상단 태그)<data(.js): 국내 키워드-> DOM_KW, 해외 키워드-> GBL_KW>
function updateTodayKeywords(keywords) {
    const bubbleRow = document.getElementById('todayKeywords');
    if (!bubbleRow) return;
    bubbleRow.innerHTML = '';
    keywords.slice(0, 5).forEach((kw, index) => {
        const bubble = document.createElement('span');
        bubble.className = 'bubble big' + (index === 0 ? ' hot' : '');
        bubble.textContent = kw.keyword;
        bubbleRow.appendChild(bubble);
    });
}
//메트릭 카드 데이터, 렌더 함수는 dashboard.html의 getSentiRatios(sectors)호출)
const krSectors=[{name:"반도체",normal:18,today:41,articles:[{title:"삼성전자, HBM3E 12단 양산",source:"전자신문",tag:"긍정"},{title:"SK하이닉스, 엔비디아 HBM 공급",source:"연합뉴스",tag:"긍정"},{title:"美 반도체법 보조금 지연",source:"로이터",tag:"부정"}]},{name:"2차전지",normal:22,today:39,articles:[{title:"LG엔솔, CATL 특허 분쟁",source:"한국경제",tag:"중립"},{title:"포스코퓨처엠, 북미 증설",source:"매일경제",tag:"긍정"}]},{name:"바이오",normal:15,today:29,articles:[{title:"셀트리온, EMA 품목허가",source:"바이오타임즈",tag:"긍정"},{title:"알테오젠, 기술이전",source:"헬스코리아",tag:"긍정"}]},{name:"환율",normal:16,today:31,articles:[{title:"원/달러 1,380원 돌파",source:"파이낸셜뉴스",tag:"부정"},{title:"한은, 외환시장 조치",source:"뉴시스",tag:"중립"}]},{name:"AI",normal:20,today:45,articles:[{title:"오픈AI, GPT-5 출시",source:"테크크런치",tag:"긍정"},{title:"AI 스타트업 투자 유치",source:"머니투데이",tag:"긍정"}]},{name:"자동차",normal:18,today:34,articles:[{title:"현대차, 美 점유율 확대",source:"아주경제",tag:"긍정"},{title:"테슬라, 사이버트럭 리콜",source:"블룸버그",tag:"부정"}]},{name:"에너지",normal:14,today:28,articles:[{title:"재생에너지 비율 25% 돌파",source:"에너지경제",tag:"긍정"},{title:"원전 수출 본격화",source:"조선비즈",tag:"긍정"}]},{name:"바이오테크",normal:12,today:26,articles:[{title:"FDA, 한국 바이오 신약",source:"바이오스펙테이터",tag:"긍정"},{title:"유전자 치료제 임상 성공",source:"서울경제",tag:"긍정"}]},{name:"소비재",normal:15,today:25,articles:[{title:"명품 소비 둔화",source:"패션비즈",tag:"중립"},{title:"편의점 PB 매출 30%↑",source:"식품음료신문",tag:"긍정"}]}];
const usSectors=[{name:"AI & Tech",normal:25,today:52,articles:[{title:"Nvidia unveils next-gen AI chip",source:"Bloomberg",tag:"긍정"},{title:"Microsoft invests $3B in AI",source:"WSJ",tag:"긍정"},{title:"AI regulation debate heats up",source:"Reuters",tag:"부정"}]},{name:"Inflation",normal:22,today:38,articles:[{title:"CPI rises 3.5% YoY",source:"FT",tag:"부정"},{title:"Fed signals rate cut delay",source:"CNBC",tag:"중립"}]},{name:"Big Tech",normal:20,today:44,articles:[{title:"Apple AI push in iOS 18",source:"TechCrunch",tag:"긍정"},{title:"Google antitrust trial",source:"Reuters",tag:"부정"}]},{name:"Energy",normal:16,today:30,articles:[{title:"Oil prices drop on supply",source:"WSJ",tag:"긍정"},{title:"Renewable energy record",source:"Bloomberg",tag:"긍정"}]},{name:"Semiconductors",normal:18,today:40,articles:[{title:"TSMC Arizona delays",source:"Nikkei",tag:"부정"},{title:"Chip demand surges for AI",source:"FT",tag:"긍정"}]},{name:"EV & Auto",normal:17,today:33,articles:[{title:"Tesla recalls 2M vehicles",source:"Reuters",tag:"부정"},{title:"Ford EV sales jump",source:"CNBC",tag:"긍정"}]},{name:"Healthcare",normal:14,today:27,articles:[{title:"Pfizer new drug approval",source:"WSJ",tag:"긍정"},{title:"Medicare price negotiations",source:"FT",tag:"중립"}]},{name:"Banking",normal:15,today:28,articles:[{title:"JPMorgan profits beat",source:"Bloomberg",tag:"긍정"},{title:"Regional bank concerns",source:"Reuters",tag:"부정"}]},{name:"Retail",normal:13,today:24,articles:[{title:"Amazon sales record",source:"CNBC",tag:"긍정"},{title:"Macy's store closures",source:"WSJ",tag:"부정"}]}];
const calendarData={kr:[{date:"4월 17일",event:"한국은행 금리 결정문",importance:"high"},{date:"4월 20일",event:"수출입 물가 지수",importance:"mid"},{date:"4월 25일",event:"1분기 GDP 잠정치",importance:"high"},{date:"4월 30일",event:"산업생산 및 소매판매",importance:"mid"},{date:"5월 2일",event:"소비자물가(CPI) 발표",importance:"high"},{date:"5월 10일",event:"고용동향",importance:"mid"}],us:[{date:"Apr 17",event:"FOMC Minutes",importance:"high"},{date:"Apr 19",event:"Weekly Jobless Claims",importance:"mid"},{date:"Apr 25",event:"GDP Preliminary",importance:"high"},{date:"Apr 26",event:"PCE Price Index",importance:"high"},{date:"May 1",event:"ISM Manufacturing PMI",importance:"mid"},{date:"May 3",event:"Nonfarm Payrolls",importance:"high"}]};
// 메트릭 카드 4개_계산
function getSentiRatios(sectors){let p=0,n=0,neu=0,t=0;sectors.forEach(s=>s.articles.forEach(a=>{t++;if(a.tag==='긍정')p++;else if(a.tag==='부정')n++;else neu++;}));if(t===0)return{pos:33.3,neu:33.3,neg:33.3};return{pos:(p/t)*100,neu:(neu/t)*100,neg:(n/t)*100};}
function getSectorStack(sectors){return sectors.map(s=>{let pos=0,neg=0,t=s.articles.length;s.articles.forEach(a=>{if(a.tag==='긍정')pos++;else if(a.tag==='부정')neg++;});return{name:s.name,pos:t?(pos/t)*100:0,neg:t?(neg/t)*100:0};});}

// 오늘의 핫이슈 렌더 함수
function renderHotIssueGrid(cid, sectors) {
  const c = document.getElementById(cid);
  if (!c) return;
  const items = Array.isArray(sectors) ? sectors.filter(Boolean) : [];
  if (!items.length) {
    c.innerHTML = '<div style="color:var(--sub);font-size:13px;padding:18px 24px 24px;">핫이슈 데이터 없음</div>';
    return;
  }
  const getTitle = item => item.keyword || item.name || '-';
  const getCount = item => Number(item.count || item.totalNews || (item.articles ? item.articles.length : 0) || item.today || 0);
  const maxCount = Math.max(...items.map(getCount), 1);
  const cards = items.slice(0, 6).map(item => {
    const title = getTitle(item);
    const count = getCount(item);
    const weekAvg = Number(item.week_avg || item.weekAvg || item.normal || 0);
    const change = Number(item.change || 0);
    const width = Math.max((count / maxCount) * 100, count > 0 ? 4 : 0);
    const detailText = change
      ? `7일 평균 ${weekAvg.toFixed(1)}건 · 변화율 ${change > 0 ? '+' : ''}${change.toFixed(1)}%`
      : '클릭 시 검색 결과 보기';
    const safeTitle = _esc(title);
    const attrTitle = safeTitle.replace(/"/g, '&quot;');
    return `<div class="hi-card" data-keyword="${attrTitle}"><div class="hic-kw"><span>${safeTitle}</span><span class="hic-badge">📰 ${count}건</span></div><div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div><div class="hic-sub"><i class="fas fa-magnifying-glass" style="margin-right:4px;color:var(--teal);"></i>${detailText}</div></div>`;
  }).join('');
  c.innerHTML = `<div class="hot-issue-grid">${cards}</div>`;
  document.querySelectorAll(`#${cid} .hi-card`).forEach(card => card.addEventListener('click', () => {
    openAnalysisOverlay(card.dataset.keyword);
  }));
}
// 급등 기사 성향 분석 렌더 함수 <data(.js): .normal, .today, .articles>
function renderTrendAnalysis(cid,sectors){const c=document.getElementById(cid);if(!c)return;const items=Array.isArray(sectors)?sectors.filter(Boolean):[];c.innerHTML=items.map(s=>{const articles=Array.isArray(s.articles)?s.articles:[];const d=s.today-s.normal,a=d>=0?'▲':'▼';return`<div class="trend-card" data-sector='${JSON.stringify({...s,articles})}'><div class="tc-head"><div class="tc-name">${s.name}</div><div class="tc-badge">📰 ${articles.length}건</div></div><div class="tc-delta" style="color:${d>=0?'var(--pos)':'var(--neg)'}"><span>${a}</span> ${Math.abs(d)}%p 변화</div><div class="tc-bars"><div class="tc-bar-box"><div class="tiny">평소</div><div class="mini-track"><div class="mini-fill" style="width:${s.normal}%;background:var(--neu);"></div></div><div class="tiny">${s.normal}%</div></div><div class="tc-bar-box"><div class="tiny">오늘</div><div class="mini-track"><div class="mini-fill" style="width:${s.today}%;background:var(--teal);"></div></div><div class="tiny">${s.today}%</div></div></div></div>`;}).join('');document.querySelectorAll(`#${cid} .trend-card`).forEach(c=>c.addEventListener('click',()=>{const s=JSON.parse(c.dataset.sector);const articles=Array.isArray(s.articles)?s.articles:[];alert(`📊 [${s.name}]\n변화율: ${s.today-s.normal}%p\n\n${articles.map(a=>`• ${a.title} (${a.source} / ${a.tag})`).join('\n')}`);}));}
// 시장 전체 성향 비율 렌더 함수(data(.js): getSentiRatios()가 계산)
function renderMarketSentiment(cid,sectors){const{pos,neu,neg}=getSentiRatios(sectors);const sz=200,r=sz/2,inn=58,c=r;const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("width",sz);svg.setAttribute("height",sz);svg.setAttribute("viewBox",`0 0 ${sz} ${sz}`);let st=0;[[pos,'#2ECC71'],[neu,'#8E9CC5'],[neg,'#E74C3C']].forEach(([val,col])=>{if(val===0)return;
if(val>=100){
  const fc=document.createElementNS("http://www.w3.org/2000/svg","circle");
  fc.setAttribute("cx",c);fc.setAttribute("cy",c);
  fc.setAttribute("r",r);fc.setAttribute("fill",col);
  svg.appendChild(fc);st+=360;return;
}
const ang=(val/100)*360,end=st+ang;const rS=(st-90)*Math.PI/180,rE=(end-90)*Math.PI/180;const x1=c+r*Math.cos(rS),y1=c+r*Math.sin(rS),x2=c+r*Math.cos(rE),y2=c+r*Math.sin(rE);const lg=ang>180?1:0;const p=document.createElementNS("http://www.w3.org/2000/svg","path");p.setAttribute("d",`M ${c} ${c} L ${x1} ${y1} A ${r} ${r} 0 ${lg} 1 ${x2} ${y2} Z`);p.setAttribute("fill",col);p.setAttribute("stroke","white");p.setAttribute("stroke-width","3");svg.appendChild(p);st=end;});const ic=document.createElementNS("http://www.w3.org/2000/svg","circle");ic.setAttribute("cx",c);ic.setAttribute("cy",c);ic.setAttribute("r",inn);ic.setAttribute("fill","#f0f6ff");svg.appendChild(ic);
const items=[{n:'긍정',p:pos,c:'#2ECC71'},{n:'중립',p:neu,c:'#8E9CC5'},{n:'부정',p:neg,c:'#E74C3C'}];const top=items.reduce((m,i)=>i.p>m.p?i:m,items[0]);
document.getElementById(cid).innerHTML=`<div style="display:flex;flex-direction:column;align-items:center;height:100%"><div class="market-donut">${svg.outerHTML}<div class="donut-center"><span class="pulse-num" style="font-size:26px;color:${top.c};">${Math.round(top.p)}%</span><span style="font-size:11px;color:var(--sub);margin-top:2px;">${top.n}</span></div></div><div class="market-legend">${items.map(i=>`<span class="leg-item"><span class="leg-dot" style="background:${i.c};"></span>${i.n} ${Math.round(i.p)}%</span>`).join('')}</div></div>`;}
// 섹터별 긍/부정 비율<data(.js): getSectorStack()가 계산>
function renderSectorStack(cid,sectors){
  const stacks=getSectorStack(sectors),f4=stacks.slice(0,4),rest=stacks.slice(4);
  const c=document.getElementById(cid);
  if(!c)return;
  let html=f4.map(s=>`<div class="stack-item"><div class="stack-label"><span>${s.name}</span><span style="font-size:11px;color:var(--sub);">긍정 ${Math.round(s.pos)}% · 부정 ${Math.round(s.neg)}%</span></div><div class="stack-bar-bg"><div class="stack-pos" style="width:${s.pos}%;"></div><div class="stack-neg" style="width:${s.neg}%;"></div></div></div>`).join('');
  let moreBtnId = cid + 'MoreBtn';
  if(rest.length>0) html+=`<div class="more-btn"><button id="${moreBtnId}">더보기 (${rest.length}개)</button></div>`;
  c.innerHTML=html;
  const mb=document.getElementById(moreBtnId);
  if(mb) mb.addEventListener('click',()=>{
    const mc=document.getElementById('moreModalContent');
    if(mc) mc.innerHTML=rest.map(s=>`<div class="stack-item" style="margin-bottom:12px;"><div class="stack-label"><span>${s.name}</span><span>${Math.round(s.pos)}% / ${Math.round(s.neg)}%</span></div><div class="stack-bar-bg"><div class="stack-pos" style="width:${s.pos}%;"></div><div class="stack-neg" style="width:${s.neg}%;"></div></div></div>`).join('');
    document.getElementById('moreModal').classList.add('show');
  });
}
// 경제 주요 일정<data(.js): calendarData객체>
function renderEcoCalendar(cid,cc){const evts=calendarData[cc];document.getElementById(cid).innerHTML=evts.map(ev=>{let ic='imp-l',it='낮음',bdr='var(--teal)';if(ev.importance==='high'){ic='imp-h';it='중요';bdr='var(--neg)';}else if(ev.importance==='mid'){ic='imp-m';it='중간';bdr='var(--gold)';}return`<div class="sch-item" style="border-left-color:${bdr};"><div class="sch-date">${ev.date}</div><div class="sch-info"><div class="sch-name">${ev.event}</div><span class="sch-imp ${ic}">${it}</span></div></div>`;}).join('');}

function genKREcoData(){const today=new Date().toISOString().slice(0,10);let seed=0;for(let i=0;i<today.length;i++)seed+=today.charCodeAt(i);const cdTr=[3.45,3.44,3.43,3.42,3.42+(Math.sin(seed)*.1)];const usdTr=[1375,1378,1380,1382,1382+(Math.sin(seed+1)*5)];const kospiTr=[2670,2678,2683,2685,2685+(Math.sin(seed+2)*15)];const kosdaqTr=[880,878,877,877,877+(Math.sin(seed+3)*6)];return[{name:"GDP 성장률_전분기비",value:cdTr[4].toFixed(2)+"%",change:((cdTr[4]-cdTr[3])>=0?"+":"")+((cdTr[4]-cdTr[3]).toFixed(2))+"%",changeType:cdTr[4]-cdTr[3]>=0?"up":"down",trend:cdTr},{name:"소비자물가상승률(CPI)",value:usdTr[4].toFixed(1)+"%",change:((usdTr[4]-usdTr[3])>=0?"+":"")+((usdTr[4]-usdTr[3]).toFixed(1))+"%",changeType:usdTr[4]-usdTr[3]>=0?"up":"down",trend:usdTr},{name:"실업률 Apr",value:kospiTr[4].toFixed(1),change:((((kospiTr[4]-kospiTr[3])/kospiTr[3])*100)>=0?"+":"")+(((kospiTr[4]-kospiTr[3])/kospiTr[3])*100).toFixed(2)+"%",changeType:kospiTr[4]>=kospiTr[3]?"up":"down",trend:kospiTr},{name:"경상수지 Mar",value:kosdaqTr[4].toFixed(1),change:((((kosdaqTr[4]-kosdaqTr[3])/kosdaqTr[3])*100)>=0?"+":"")+(((kosdaqTr[4]-kosdaqTr[3])/kosdaqTr[3])*100).toFixed(2)+"%",changeType:kosdaqTr[4]>=kosdaqTr[3]?"up":"down",trend:kosdaqTr}];}
function genUSEcoData(){const today=new Date().toISOString().slice(0,10);let seed=0;for(let i=0;i<today.length;i++)seed+=today.charCodeAt(i);const goldTr=[4820,4790,4740,4710,4676+(Math.sin(seed)*5)];const oilTr=[91.2,92.5,93,94,94.94+(Math.sin(seed+1)*1.5)];const spTr=[7000,7030,7060,7080,7108+(Math.sin(seed+2)*15)];const gdpTr=[1.4,1.2,.9,.7,.5+(Math.sin(seed+3)*.1)];return[{name:"GDP",value:goldTr[4].toFixed(2)+"%",change:(((goldTr[4]-goldTr[3])/goldTr[3])*100>=0?"+":"")+(((goldTr[4]-goldTr[3])/goldTr[3])*100).toFixed(2)+"%",changeType:goldTr[4]>=goldTr[3]?"up":"down",trend:goldTr},{name:"CPI",value:oilTr[4].toFixed(2)+"%",change:(((oilTr[4]-oilTr[3])/oilTr[3])*100>=0?"+":"")+(((oilTr[4]-oilTr[3])/oilTr[3])*100).toFixed(2)+"%",changeType:oilTr[4]>=oilTr[3]?"up":"down",trend:oilTr},{name:"Unemployment rate",value:spTr[4].toFixed(2),change:(((spTr[4]-spTr[3])/spTr[3])*100>=0?"+":"")+(((spTr[4]-spTr[3])/spTr[3])*100).toFixed(2)+"%",changeType:spTr[4]>=spTr[3]?"up":"down",trend:spTr},{name:"Nonfarm payrolls",value:gdpTr[4].toFixed(1)+"%",change:((gdpTr[4]-gdpTr[3])>=0?"+":"")+(gdpTr[4]-gdpTr[3]).toFixed(1)+"%p",changeType:gdpTr[4]>=gdpTr[3]?"up":"down",trend:gdpTr}];}

let ecoData={kr:genKREcoData(),us:genUSEcoData()};
// 주요 경제 지표(GDP, CPI,실업률 등)<data(.js): genKREcoData() 및 genUSEcoData()>
function renderEcoIndicators(cid,cc){const inds=ecoData[cc];const c=document.getElementById(cid);if(!c)return;c.innerHTML=inds.map(ind=>{const mx=Math.max(...ind.trend);const bars=ind.trend.map(v=>(v/mx)*24);return`<div class="ind-card"><div class="ind-name">${ind.name}</div><div class="ind-val">${ind.value}<span class="ind-chg ${ind.changeType}">${ind.change}</span></div><div class="spark">${bars.map(h=>`<div class="spark-b" style="height:${h}px;"></div>`).join('')}</div></div>`;}).join('');}

// ========== 사이드바 이벤트 바인딩 (공통) ==========
function bindSidebarEvents() {
  // 마이페이지 버튼
  const mypageBtn = document.getElementById('mypageLabel');
  if (mypageBtn) {
    // 중복 이벤트 방지를 위해 기존 리스너 제거 후 추가
    mypageBtn.removeEventListener('click', mypageBtn._listener);
    mypageBtn._listener = () => location.href = 'mypage.html';
    mypageBtn.addEventListener('click', mypageBtn._listener);
  }

  // 로그아웃 버튼
  const logoutBtn = document.getElementById('sidebarLogoutBtn');
  if (logoutBtn) {
    logoutBtn.removeEventListener('click', logoutBtn._listener);
    logoutBtn._listener = () => doLogout();
    logoutBtn.addEventListener('click', logoutBtn._listener);
  }
}