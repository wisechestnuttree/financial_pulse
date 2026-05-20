// admin.js
// ── 누락된 상수 정의
const ADM_SUBJECTS = ['전체','crawl','system','ml','user'];
const ADM_LEVELS   = ['ALL','INFO','WARNING','ERROR','DEBUG'];

function _genLogs(n, subjectFilter){
  const subjects = subjectFilter && subjectFilter!=='전체' ? [subjectFilter] : ['크롤링','데이터관리','비정형수치','로그인'];
  const levels   = ['INFO','INFO','INFO','WARN','ERROR','SUCCESS','DEBUG'];
  const messages = {
    '크롤링':[
      '[START] 뉴스 크롤링 배치 시작 | 대상: 네이버, 다음, 연합뉴스',
      'Crawling: https://n.news.naver.com/article/001/0012345678 | 제목: 삼성전자 실적 발표 | 국가: KR | 상태: OK',
      'Crawling: https://n.news.naver.com/article/030/0009876543 | 제목: 코스피 2600선 돌파 | 국가: KR | 상태: OK',
      '[WARN] 연결 타임아웃 | url: https://n.news.naver.com/article/055/0001234567 | retry: 1/3',
      '[ERROR] 크롤링 실패 | url: https://n.news.naver.com/article/055/0001234567 | 제목: 원달러 환율 급등 | 국가: KR',
      '[END] 크롤링 완료 | 총 312건 시도 | 성공: 308 | 실패: 4 | error_cnt: 4',
    ],
    '데이터관리':[
      '[START] ES 인덱스 정합성 검사 시작 | 범위: 어제 00:00 ~ 오늘 00:00',
      'ES newsStorage 조회 완료 | save_cnt: 308',
      '크롤링 로그 crawl_cnt: 312 | save_cnt: 308 | missing_cnt: 4',
      '[WARN] 누락 감지 | missing_cnt=4 > 0 | 누락 URL 목록 생성',
      'URL 대조 완료 | 누락 URL: 4건 확인 | 재수집 시도',
      '[ERROR] 재수집 실패 | url: https://n.news.naver.com/article/055/0001234567 | 원인: 404',
      '[END] ES 정합성 검사 완료 | crawl_cnt: 312 | save_cnt: 308 | missing_cnt: 4 | 미복구: 1건',
    ],
    '로그인':[
      '[INFO] 로그인 성공 | email: user@example.com | ip: 123.45.67.89 | agent: Chrome/124',
      '[INFO] 로그인 성공 | email: demo@finance.com | ip: 98.76.54.32 | agent: Safari/17',
      '[WARN] 로그인 실패 (2/5) | email: unknown@test.com | ip: 111.22.33.44 | reason: 비밀번호 불일치',
      '[WARN] 로그인 실패 (4/5) | email: demo@finance.com | ip: 55.66.77.88 | reason: 비밀번호 불일치',
      '[ERROR] 계정 잠금 | email: hacker@bad.com | ip: 192.168.1.100 | reason: 5회 연속 실패',
      '[INFO] 로그아웃 | email: user@example.com | ip: 123.45.67.89 | session: 38분',
      '[INFO] 임시 비밀번호 발급 | email: forgot@finance.com | ip: 77.88.99.10',
      '[INFO] 비밀번호 변경 완료 | email: forgot@finance.com | ip: 77.88.99.10',
      '[WARN] 만료 토큰 접근 시도 | email: old@finance.com | ip: 33.44.55.66',
      '[ERROR] 존재하지 않는 계정 로그인 시도 | email: ghost@nowhere.com | ip: 202.10.20.30',
    ],
    '비정형수치':[
      '[START] 비정형 성향치 검사 시작 (03:00 배치)',
      '비정형 감지: { title:"반도체 급등", url:"https://...", tend_score: 98.7, tendency:"매우긍정" }',
      'ML 재처리 시도 | url: https://n.news.naver.com/article/030/0003270001',
      '[WARN] 재처리 후에도 비정형 성향치 유지 | tend_score: 96.2 | 관리자 검토 필요',
      '[END] 비정형 성향치 검사 완료 | 감지: 7건 | 자동보정: 4건 | 검토필요: 3건',
    ]
  };
  const logs = [];
  const now = Date.now();
  for(let i=0;i<n;i++){
    const subj = subjects[Math.floor(Math.random()*subjects.length)];
    const lvl  = levels[Math.floor(Math.random()*levels.length)];
    const msgs = messages[subj];
    const msg  = msgs[Math.floor(Math.random()*msgs.length)];
    logs.push({
      id: 'LOG-'+String(i+1).padStart(5,'0'),
      timestamp: new Date(now - Math.random()*86400000*3).toISOString().replace('T',' ').slice(0,19),
      subject: subj,
      level: lvl,
      message: msg,
      raw: JSON.stringify({id:i+1, subject:subj, level:lvl, message:msg, host:'fp-server-01', pid:1234+i})
    });
  }
  return logs.sort((a,b)=>b.timestamp.localeCompare(a.timestamp));
}

let _admLogs = [];

// ── 실제 API에서 로그 로드
async function _fetchAdminLogs(params = {}) {
  const body = {
    level      : params.level && params.level !== 'ALL' ? params.level : null,
    subject    : params.subject && params.subject !== '전체' ? params.subject : null,
    start_time : params.from || null,
    end_time   : params.to || null,
    keyword    : params.keyword || null,
    size       : 200
  };

  // null 값 제거
  Object.keys(body).forEach(key => body[key] === null && delete body[key]);

  const res = await fetch(BASE_URL + '/logs/search', {
    method     : 'POST',
    headers    : { 'Content-Type': 'application/json' },
    credentials: 'include',
    body       : JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok || data.success === false) throw new Error(data.message || '로그 조회 실패');

  const payload = data.data || data;
  return (payload.logs || []).map((l, idx) => ({
    id       : l.log_id || `LOG-${String(idx + 1).padStart(5, '0')}`,
    timestamp: (l.timestamp || '').replace('T', ' ').slice(0, 19),
    subject  : l.subject  || '',
    level    : l.level    || 'INFO',
    message  : l.message  || '',
    raw      : JSON.stringify(l.extra || {})
  }));
}

let _tailInterval = null;

// ── 레벨별 뱃지 HTML생성
function _lvlBadge(lvl){
  const m={'INFO':'log-info','WARN':'log-warn','WARNING':'log-warn','ERROR':'log-error','DEBUG':'log-debug','SUCCESS':'log-success'};
  return `<span class="log-badge ${m[lvl]||'log-debug'}">${lvl}</span>`;
}

// ── 로그 필터링 (레벨, 주체, 키워드, 날짜)
function _filterLogs(logs, level, subject, keyword, from, to){
  return logs.filter(l=>{
    if(level && level!=='ALL' && l.level!==level) return false;
    if(subject && subject!=='전체' && l.subject!==subject) return false;
    if(keyword && !l.message.toLowerCase().includes(keyword.toLowerCase()) && !l.id.includes(keyword)) return false;
    if(from && l.timestamp < from) return false;
    if(to && l.timestamp > to) return false;
    return true;
  });
}

// 로그 통계 계산
function _calcStats(logs){
  const total = logs.length;
  const byLevel = {INFO:0,WARNING:0,ERROR:0,DEBUG:0};
  logs.forEach(l=>{ if(byLevel[l.level]!==undefined) byLevel[l.level]++; });
  return {total, ...byLevel};
}

// ── 로그 뷰어 페이지 (탭, 필터 바, 통계 카드, 로그 테이블)
function _renderLogPage(page){
  const main = document.getElementById('admMain');
  const esLabel = {'전체':'전체 ES','crawl':'크롤링 ES','system':'시스템 ES','ml':'머신러닝 ES','user':'로그인 ES'};

  main.innerHTML = `
    <h2 style="font-size:20px;font-weight:900;color:var(--navy);display:flex;align-items:center;gap:10px;">
      <i class="fas fa-list" style="color:var(--teal);"></i> 로그 뷰어
    </h2>

    <div class="adm-tabs" id="admEsTabs">
      ${ADM_SUBJECTS.map(s=>`<button class="adm-tab${s==='전체'?' active':''}" data-es="${s}">${esLabel[s]||s}</button>`).join('')}
    </div>

    <div class="adm-filter-bar">
      <div>
        <label>레벨</label>
        <select id="admLevelFilter">
          ${ADM_LEVELS.map(l=>`<option value="${l}">${l}</option>`).join('')}
        </select>
      </div>
      <div>
        <label>주체</label>
        <select id="admSubjectFilter">
          ${ADM_SUBJECTS.map(s=>`<option value="${s}">${s}</option>`).join('')}
        </select>
      </div>
      <div>
        <label>시작</label>
        <input type="datetime-local" id="admFromFilter">
      </div>
      <div>
        <label>종료</label>
        <input type="datetime-local" id="admToFilter">
      </div>
      <div class="adm-search-wrap">
        <input type="text" id="admKeyword" placeholder="키워드 검색 (메시지, ID...)">
        <button class="adm-btn adm-btn-primary" id="admSearchBtn"><i class="fas fa-magnifying-glass"></i> 검색</button>
        <button class="adm-btn adm-btn-ghost" id="admResetBtn">초기화</button>
      </div>
    </div>

    <div class="adm-stats-grid" id="admStatsGrid"></div>

    <div class="adm-log-wrap">
      <div class="adm-log-toolbar">
        <div class="alt-title"><i class="fas fa-table-list" style="color:var(--teal);"></i> 로그 목록 <span id="admLogCount" style="font-size:12px;color:var(--sub);font-weight:600;"></span></div>
        <div class="alt-actions">
          <button class="adm-btn adm-btn-ghost" id="admExportBtn"><i class="fas fa-download"></i> CSV 내보내기</button>
        </div>
      </div>
      <div style="overflow-x:auto;">
        <table class="adm-table" id="admLogTable">
          <thead><tr><th>타임스탬프</th><th>주체</th><th>레벨</th><th>메시지</th></tr></thead>
          <tbody id="admLogBody"></tbody>
        </table>
      </div>
    </div>
  `;

  let curEs = '전체';
  let curFiltered = [..._admLogs];

  function _renderStats(logs){
    const s = _calcStats(logs);
    document.getElementById('admStatsGrid').innerHTML = `
      <div class="adm-stat-card asc-info"><div class="asc-label">총 로그</div><div class="asc-val">${s.total.toLocaleString()}</div><div class="asc-sub">전체 기간</div></div>
      <div class="adm-stat-card asc-err"><div class="asc-label">ERROR</div><div class="asc-val">${s.ERROR}</div><div class="asc-sub">즉시 확인 필요</div></div>
      <div class="adm-stat-card asc-warn"><div class="asc-label">WARNING</div><div class="asc-val">${s.WARNING}</div><div class="asc-sub">모니터링 필요</div></div>
      <div class="adm-stat-card asc-ok"><div class="asc-label"> INFO/DEBUG</div><div class="asc-val">${s.INFO + s.DEBUG}</div><div class="asc-sub">정상 완료</div></div>
    `;
  }

  function _renderTable(logs){
    curFiltered = logs;
    document.getElementById('admLogCount').innerText = `(${logs.length.toLocaleString()}건)`;
    const tbody = document.getElementById('admLogBody');
    if(!logs.length){ tbody.innerHTML=`<td><td colspan="5" style="text-align:center;padding:30px;color:var(--sub);">검색 결과가 없습니다.</td></tr>`; return; }
    tbody.innerHTML = logs.slice(0,200).map(l=>`
      <tr>
        <td style="white-space:nowrap;font-family:monospace;font-size:11.5px;color:var(--sub);">${l.timestamp}</td>
        <td><span style="font-weight:700;font-size:12px;">${l.subject}</span></td>
        <td>${_lvlBadge(l.level)}</td>
        <td class="log-msg">${l.message}</td>
      </tr>`).join('');
    _renderStats(logs);
  }

  async function _doFilter(){
    const level   = document.getElementById('admLevelFilter').value;
    const subject = curEs==='전체' ? document.getElementById('admSubjectFilter').value : curEs;
    const kw      = document.getElementById('admKeyword').value.trim();
    const from    = document.getElementById('admFromFilter').value;
    const to      = document.getElementById('admToFilter').value;

    // 한글 → 영문 변환
    const esSubject = subject === '전체' ? null : subject;

    // 항상 API 재호출 (레벨/주체/날짜/키워드 서버에서 필터링)
    const logs = await _fetchAdminLogs({
      subject: esSubject || null,
      level  : level !== 'ALL' ? level : null,
      from   : from || null,
      to     : to   || null,
      keyword: kw   || null,
    });
    _renderTable(logs);
  }

  document.getElementById('admEsTabs').addEventListener('click', async e=>{
  const btn = e.target.closest('.adm-tab');
  if(!btn) return;
  document.querySelectorAll('.adm-tab').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  curEs = btn.dataset.es;
  document.getElementById('admSubjectFilter').value = curEs;

  const esSubject = curEs === '전체' ? null : curEs;
  const logs = await _fetchAdminLogs({ subject: esSubject });

  _admLogs = logs;
  _doFilter();
});

  document.getElementById('admSearchBtn').addEventListener('click', async () => _doFilter());
  document.getElementById('admResetBtn').addEventListener('click', async ()=>{
  ['admLevelFilter','admSubjectFilter'].forEach(id=>document.getElementById(id).value=id.includes('Level')?'ALL':'전체');
  ['admKeyword','admFromFilter','admToFilter'].forEach(id=>document.getElementById(id).value='');
  curEs='전체';
  document.querySelectorAll('.adm-tab').forEach((b,i)=>{b.classList.toggle('active',i===0);});
  const logs = await _fetchAdminLogs();
  _admLogs = logs;
  _doFilter();
});
  document.getElementById('admKeyword').addEventListener('keydown', e=>{ if(e.key==='Enter') _doFilter(); });

  document.getElementById('admExportBtn').addEventListener('click', ()=>{
    const rows = [['ID','타임스탬프','주체','레벨','메시지'], ...curFiltered.map(l=>[l.id,l.timestamp,l.subject,l.level,'"'+l.message.replace(/"/g,'""')+'"'])];
    const csv = rows.map(r=>r.join(',')).join('\n');
    const a = document.createElement('a');
    a.href = 'data:text/csv;charset=utf-8,\uFEFF'+encodeURIComponent(csv);
    a.download = 'fp_logs_'+new Date().toISOString().slice(0,10)+'.csv';
    a.click();
  });

  _renderTable(_admLogs);
}

// ── 실시간 모니터 페이지 (tail 로그 박스, 통계, 시작/중단 버튼)
function _renderRealtimePage(){
  const main = document.getElementById('admMain');
  main.innerHTML = `
    <h2 style="font-size:20px;font-weight:900;color:var(--navy);display:flex;align-items:center;gap:10px;">
      <i class="fas fa-satellite-dish" style="color:var(--teal);"></i> 실시간 모니터
      <span id="tailStatus" style="font-size:12px;font-weight:700;color:var(--pos);background:rgba(46,204,113,.1);border:1px solid rgba(46,204,113,.2);border-radius:999px;padding:3px 10px;">● LIVE</span>
    </h2>
    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
      <label style="font-size:13px;font-weight:700;color:var(--sub);">필터:</label>
      <select id="tailLevelFilter" style="background:var(--panel);border:1.5px solid var(--pbl);border-radius:8px;padding:7px 12px;font-size:12px;font-family:inherit;">
        ${ADM_LEVELS.map(l=>`<option>${l}</option>`).join('')}
      </select>
      <select id="tailSubjectFilter" style="background:var(--panel);border:1.5px solid var(--pbl);border-radius:8px;padding:7px 12px;font-size:12px;font-family:inherit;">
        ${ADM_SUBJECTS.map(s=>`<option>${s}</option>`).join('')}
      </select>
      <button class="adm-btn adm-btn-ghost" id="tailClearBtn"><i class="fas fa-trash"></i> 지우기</button>
      <button class="adm-btn adm-btn-danger" id="tailStopBtn"><i class="fas fa-stop"></i> 중단</button>
    </div>
    <div class="adm-tail" id="admTailBox">
      <div style="color:rgba(0,181,173,.6);font-size:12px;margin-bottom:8px;">── Financial Pulse Log Tail ── [${new Date().toLocaleString()}] ──</div>
    </div>
    <div class="adm-stats-grid" id="tailStatsGrid">
      <div class="adm-stat-card asc-info"><div class="asc-label">수신 로그</div><div class="asc-val" id="tailCntTotal">0</div><div class="asc-sub">누적</div></div>
      <div class="adm-stat-card asc-err"><div class="asc-label">ERROR</div><div class="asc-val" id="tailCntErr">0</div></div>
      <div class="adm-stat-card asc-warn"><div class="asc-label">WARN</div><div class="asc-val" id="tailCntWarn">0</div></div>
      <div class="adm-stat-card asc-ok"><div class="asc-label">SUCCESS</div><div class="asc-val" id="tailCntOk">0</div></div>
    </div>
  `;

  let running=true, total=0, errCnt=0, warnCnt=0, okCnt=0;
  const box = document.getElementById('admTailBox');
  const lvlClass={'INFO':'tail-info','WARN':'tail-warn','ERROR':'tail-error','DEBUG':'tail-info','SUCCESS':'tail-success'};

  function _addTailLine(log){
    const lvl = document.getElementById('tailLevelFilter').value;
    const subj = document.getElementById('tailSubjectFilter').value;
    if(lvl!=='ALL' && log.level!==lvl) return;
    if(subj!=='전체' && log.subject!==subj) return;
    const line = document.createElement('div');
    line.className='tail-line';
    line.innerHTML=`<span class="tail-ts">${log.timestamp}</span><span class="tail-subj">[${log.subject}]</span><span class="${lvlClass[log.level]||'tail-info'}">[${log.level}]</span> ${log.message}`;
    box.appendChild(line);
    while(box.children.length > 301) box.children[1].remove();
    box.scrollTop = box.scrollHeight;
    total++; if(log.level==='ERROR')errCnt++; if(log.level==='WARN')warnCnt++; if(log.level==='SUCCESS')okCnt++;
    document.getElementById('tailCntTotal').innerText=total;
    document.getElementById('tailCntErr').innerText=errCnt;
    document.getElementById('tailCntWarn').innerText=warnCnt;
    document.getElementById('tailCntOk').innerText=okCnt;
  }

  _admLogs.slice(0,10).reverse().forEach(_addTailLine);

  if(_tailInterval) clearInterval(_tailInterval);
  _tailInterval = setInterval(()=>{
    if(!running) return;
    const fakes = _genLogs(1);
    fakes.forEach(l=>{ l.timestamp=new Date().toISOString().replace('T',' ').slice(0,19); _addTailLine(l); });
  }, 2000);

  document.getElementById('tailClearBtn').addEventListener('click',()=>{ while(box.children.length>1) box.lastChild.remove(); });
  document.getElementById('tailStopBtn').addEventListener('click',()=>{
    running=!running;
    const btn=document.getElementById('tailStopBtn');
    const sts=document.getElementById('tailStatus');
    btn.innerHTML=running?'<i class="fas fa-stop"></i> 중단':'<i class="fas fa-play"></i> 재개';
    btn.className='adm-btn '+(running?'adm-btn-danger':'adm-btn-primary');
    sts.innerHTML=running?'● LIVE':'● PAUSED';
    sts.style.color=running?'var(--pos)':'var(--gold)';
    sts.style.background=running?'rgba(46,204,113,.1)':'rgba(201,162,39,.1)';
  });
}

// ── 크롤링 관리 페이지 (오류 로그 테이블, 재시도 버튼)
async function _renderCrawlerPage() {
  const main = document.getElementById('admMain');

  main.innerHTML = `<div style="padding:40px;text-align:center;color:var(--sub);"><i class="fas fa-spinner fa-spin"></i> 불러오는 중...</div>`;

  // 통계 카드 — GET /crawl/summary
  let summary = { total: 0, error: 0, warning: 0, latest: null };
  try {
    const res = await fetch(BASE_URL + '/crawl/summary', {
      method: 'GET',
      credentials: 'include',
    });
    const data = await res.json();
    if (data.success !== false) summary = data.data || data;
  } catch(e) { console.warn('crawl summary 실패:', e); }

  // 오류 로그 — subject=crawl 전체 로그
  let crawlLogs = [];
  try {
    crawlLogs = await _fetchAdminLogs({ subject: 'crawl' });
  } catch(e) { console.warn('crawl logs 실패:', e); }

  const lastRun = summary.latest ? summary.latest.replace('T', ' ').slice(0, 16) : '-';
  const errorLogs = crawlLogs.filter(l => l.level === 'ERROR' || l.level === 'WARN' || l.level === 'WARNING');

  main.innerHTML = `
    <h2 style="font-size:20px;font-weight:900;color:var(--navy);display:flex;align-items:center;gap:10px;">
      <i class="fas fa-spider" style="color:var(--teal);"></i> 크롤링 스케줄러 관리
    </h2>
    <div class="adm-stats-grid">
      <div class="adm-stat-card asc-info"><div class="asc-label">총 로그</div><div class="asc-val">${summary.total}</div></div>
      <div class="adm-stat-card asc-err"><div class="asc-label">ERROR</div><div class="asc-val">${summary.error}</div><div class="asc-sub">재시도 대상</div></div>
      <div class="adm-stat-card asc-warn"><div class="asc-label">WARN</div><div class="asc-val">${summary.warning}</div></div>
      <div class="adm-stat-card asc-ok"><div class="asc-label">마지막 실행</div><div class="asc-val" style="font-size:14px;">${lastRun}</div><div class="asc-sub">최근 로그 기준</div></div>
    </div>
    <div class="adm-log-wrap">
      <div class="adm-log-toolbar">
        <div class="alt-title"><i class="fas fa-spider" style="color:var(--teal);"></i> 크롤링 로그 (오류 우선) <span style="font-size:12px;color:var(--sub);font-weight:600;">(${errorLogs.length}건)</span></div>
        <div class="alt-actions">
          <button class="adm-btn adm-btn-primary" id="openErrorRetryBtn"><i class="fas fa-rotate-right"></i> 오류 재시도</button>
        </div>
      </div>
      <div style="overflow-x:auto;">
        <table class="adm-table">
          <thead>
            <tr><th>타임스탬프</th><th>레벨</th><th>메시지</th></tr>
          </thead>
          <tbody>
            ${errorLogs.length ? errorLogs.slice(0, 50).map(l => `
              <tr>
                <td style="white-space:nowrap;font-family:monospace;font-size:11.5px;">${l.timestamp}</td>
                <td>${_lvlBadge(l.level)}</td>
                <td class="log-msg">${l.message}</td>
              </tr>
            `).join('') : '<tr><td colspan="3" style="text-align:center;padding:30px;color:var(--sub);">오류 로그가 없습니다.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
  `;

  const retryBtn = document.getElementById('openErrorRetryBtn');
  if (retryBtn) {
    retryBtn.addEventListener('click', openErrorRetryModal);
  }
}

// ES 인덱스 관리: 인덱스 현황, 누락 URL 목록, 재수집 버튼
async function _renderEsPage(){
  const main = document.getElementById('admMain');

  main.innerHTML = `<div style="padding:40px;text-align:center;color:var(--sub);"><i class="fas fa-spinner fa-spin"></i> 불러오는 중...</div>`;

  // 실제 API 호출 — GET /es/status
  let indices = [];
  try {
    const res = await fetch(BASE_URL + '/es/status', {
      method: 'GET',
      credentials: 'include',
    });
    const data = await res.json();
    indices = (data.data || data).indices || [];
  } catch(e) { console.warn('ES status 실패:', e); }

  // missing_cnt > 0 인 인덱스만 누락 URL 섹션 표시
  const missingIndices = indices.filter(idx => idx.missing_cnt > 0);

  main.innerHTML = `
    <div class="page-title">
      <i class="fas fa-database" style="color:var(--teal);"></i> ES 인덱스 관리
    </div>
    <div class="adm-log-wrap">
      <div class="adm-log-toolbar"><div class="alt-title">인덱스 현황</div></div>
      <div style="overflow-x:auto;">
        <table class="adm-table" style="min-width: 800px;">
          <thead>
            <tr>
              <th style="width:20%">인덱스명</th>
              <th style="width:15%">문서수</th>
              <th style="width:15%">crawl_cnt</th>
              <th style="width:15%">save_cnt</th>
              <th style="width:15%">missing_cnt</th>
              <th style="width:12%">상태</th>
              <th style="width:8%"></th>
            </tr>
          </thead>
          <tbody>
            ${indices.map(idx => `
              <tr>
                <td><strong>${idx.index}</strong></td>
                <td>${idx.total.toLocaleString()}</td>
                <td>${idx.crawl_cnt ?? '-'}</td>
                <td>${idx.save_cnt ?? '-'}</td>
                <td style="color:${idx.missing_cnt > 0 ? 'var(--neg)' : 'inherit'};font-weight:${idx.missing_cnt > 0 ? '800' : 'normal'};">${idx.missing_cnt}</td>
                <td><span class="log-badge ${idx.status === '누락감지' ? 'log-warn' : 'log-success'}">${idx.status}</span></td>
                <td>${idx.missing_cnt > 0 ? `<button class="adm-btn adm-btn-primary recollect-btn" data-index="${idx.index}" data-missing="${idx.missing_cnt}" style="font-size:11px;">재수집</button>` : ''}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
    ${missingIndices.length > 0 ? `
    <div class="adm-log-wrap" style="margin-top:20px;">
      <div class="adm-log-toolbar"><div class="alt-title">누락 URL 목록</div></div>
      <div style="overflow-x:auto;">
        <table class="adm-table" style="min-width: 700px;">
          <thead>
            <tr>
              <th style="width:45%">URL</th>
              <th style="width:20%">제목</th>
              <th style="width:10%">국가</th>
              <th style="width:15%">상태</th>
              <th style="width:10%">액션</th>
            </tr>
          </thead>
          <tbody id="missingUrlTableBody"></tbody>
        </table>
      </div>
    </div>` : ''}
  `;

  // 재수집 버튼 이벤트
  document.querySelectorAll('.recollect-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const missingCount = btn.getAttribute('data-missing') || '0';
      const indexName = btn.getAttribute('data-index');
      showRecollectConfirmModal(missingCount, indexName);
    });
  });
}

// 재수집 확인 모달 열기
function showRecollectConfirmModal(missingCount, indexName) {
  const modal = document.getElementById('recollectConfirmModal');
  const msgSpan = document.getElementById('recollectMessage');
  msgSpan.innerText = `누락 ${missingCount}건 재수집을 시작하시겠습니까?\n인덱스: ${indexName}`;

  // 확인 버튼 이벤트 (기존 리스너 제거 후 재등록)
  const confirmBtn = document.getElementById('recollectConfirmBtn');
  const newConfirm = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
  newConfirm.addEventListener('click', () => {
    startRecollect(indexName, missingCount);
    modal.classList.remove('show');
  });

  // 취소 버튼
  const cancelBtn = document.getElementById('recollectCancelBtn');
  const newCancel = cancelBtn.cloneNode(true);
  cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
  newCancel.addEventListener('click', () => {
    modal.classList.remove('show');
  });

  modal.classList.add('show');
}

// 재수집 실행 (백엔드 호출 + UI 피드백)
async function startRecollect(indexName, missingCount) {
  // 1. 사용자에게 진행 중 표시 (토스트 또는 로딩)
  showToast(`🔄 ${indexName} 인덱스 재수집 시작 (${missingCount}건) ...`);

  // 2. 백엔드 API 호출 (실제 구현 시 URL 수정)
  try {
    // 예시: POST /api/recollect
    const response = await fetch('/api/recollect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        index: indexName,
        missingCount: parseInt(missingCount)
      })
    });
    const result = await response.json();
    if (response.ok) {
      showToast(`✅ 재수집 완료: ${result.processed}건 성공, ${result.failed}건 실패`);
      // 필요 시 테이블 새로고침 (예: _renderEsPage() 재호출)
      // _renderEsPage();
    } else {
      showToast(`❌ 재수집 실패: ${result.message || '서버 오류'}`);
    }
  } catch (err) {
    console.error(err);
    showToast(`❌ 네트워크 오류: ${err.message}`);
  }
}

// ========== 데이터 보정 관련 함수들 ==========
let currentCorrectionItem = null;
let currentCorrectionRow = null;

function getScoreColor(score) {
  const num = parseFloat(score);
  if (num >= 70) return 'var(--pos)';
  if (num >= 40) return 'var(--gold)';
  return 'var(--neg)';
}

function getTendencyClass(tendency) {
  if (tendency === '매우긍정' || tendency === '긍정') return 'log-success';
  if (tendency === '매우부정' || tendency === '부정') return 'log-error';
  return 'log-warn';
}

function getTendencyText(action) {
  const map = { 'positive': '긍정', 'neutral': '중립', 'negative': '부정' };
  return map[action] || action;
}

function showToast(message) {
  let toast = document.getElementById('customToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'customToast';
    toast.style.cssText = `
      position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
      background: #1a2a4a; color: white; padding: 12px 24px; border-radius: 40px;
      font-size: 14px; font-weight: 600; z-index: 10000; opacity: 0;
      transition: opacity 0.3s; pointer-events: none; box-shadow: 0 4px 20px rgba(0,0,0,0.2);
    `;
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.style.opacity = '1';
  setTimeout(() => { toast.style.opacity = '0'; }, 2500);
}

// 성향 변경 모달 열기
function openConfirmCorrectionModal() {
  const modal = document.getElementById('confirmCorrectionModal');
  if (!modal) return;

  // 항목 정보 표시
  document.getElementById('confirmItemTitle').innerText = currentCorrectionItem.title;
  document.getElementById('confirmItemUrl').innerText = currentCorrectionItem.url;
  document.getElementById('confirmItemScore').innerText = currentCorrectionItem.score;
  document.getElementById('confirmCurrentTendency').innerHTML = `<span class="log-badge ${getTendencyClass(currentCorrectionItem.currentTendency)}">${currentCorrectionItem.currentTendency}</span>`;

  // 버튼 이벤트 연결 (기존 리스너 제거 후 새로 등록)
  const positiveBtn = document.getElementById('actionPositive');
  const neutralBtn = document.getElementById('actionNeutral');
  const negativeBtn = document.getElementById('actionNegative');
  const deleteBtn = document.getElementById('actionDelete');

  // 긍정
  positiveBtn.replaceWith(positiveBtn.cloneNode(true));
  const newPositive = document.getElementById('actionPositive');
  newPositive.addEventListener('click', () => {
    showConfirmModal('긍정', () => {
      applyCorrection(currentCorrectionRow, '긍정');
      modal.classList.remove('show');
    });
  });

  // 중립
  neutralBtn.replaceWith(neutralBtn.cloneNode(true));
  const newNeutral = document.getElementById('actionNeutral');
  newNeutral.addEventListener('click', () => {
    showConfirmModal('중립', () => {
      applyCorrection(currentCorrectionRow, '중립');
      modal.classList.remove('show');
    });
  });

  // 부정
  negativeBtn.replaceWith(negativeBtn.cloneNode(true));
  const newNegative = document.getElementById('actionNegative');
  newNegative.addEventListener('click', () => {
    showConfirmModal('부정', () => {
      applyCorrection(currentCorrectionRow, '부정');
      modal.classList.remove('show');
    });
  });

  // 삭제
  deleteBtn.replaceWith(deleteBtn.cloneNode(true));
  const newDelete = document.getElementById('actionDelete');
  newDelete.addEventListener('click', () => {
    showConfirmModal('삭제', () => {
      if (currentCorrectionRow) currentCorrectionRow.remove();
      modal.classList.remove('show');
      showToast(`${currentCorrectionItem.title} 항목이 삭제되었습니다.`);
      currentCorrectionItem = null;
      currentCorrectionRow = null;
    }, true); // 삭제는 빨간색 스타일
  });

  modal.classList.add('show');
}

function showConfirmModal(action, onConfirm, isDelete = false) {
  const msg = isDelete
    ? `정말 "${currentCorrectionItem.title}" 항목을 삭제하시겠습니까?`
    : `현재 성향을 "${action}"(으)로 변경하시겠습니까?`;

  // 기존 tendencyConfirmModal 재사용 (또는 새로 생성)
  let confirmModal = document.getElementById('tendencyConfirmModal');
  if (!confirmModal) {
    // 없으면 동적 생성 (간단히)
    confirmModal = document.createElement('div');
    confirmModal.id = 'tendencyConfirmModal';
    confirmModal.className = 'correction-modal';
    confirmModal.innerHTML = `
      <div class="correction-box" style="width: 360px;">
        <button class="modal-close-btn" style="position: absolute; top: 12px; right: 12px; background: transparent; border: none; font-size: 24px;">&times;</button>
        <div id="tendencyConfirmMessage" style="margin-bottom: 20px; text-align: center; font-size: 16px; font-weight: 700;"></div>
        <div style="display: flex; gap: 12px;">
          <button id="tendencyConfirmCancel" class="adm-btn adm-btn-ghost" style="flex: 1;">취소</button>
          <button id="tendencyConfirmOk" class="adm-btn adm-btn-primary" style="flex: 1;">확인</button>
        </div>
      </div>
    `;
    document.body.appendChild(confirmModal);
  }

  document.getElementById('tendencyConfirmMessage').innerText = msg;
  confirmModal.classList.add('show');

  // 확인 버튼
  const okBtn = document.getElementById('tendencyConfirmOk');
  okBtn.replaceWith(okBtn.cloneNode(true));
  const newOk = document.getElementById('tendencyConfirmOk');
  newOk.onclick = () => {
    onConfirm();
    confirmModal.classList.remove('show');
  };

  // 취소 버튼
  const cancelBtn = document.getElementById('tendencyConfirmCancel');
  cancelBtn.replaceWith(cancelBtn.cloneNode(true));
  const newCancel = document.getElementById('tendencyConfirmCancel');
  newCancel.onclick = () => {
    confirmModal.classList.remove('show');
  };

  // X 닫기
  const closeX = confirmModal.querySelector('.modal-close-btn');
  closeX.onclick = () => {
    confirmModal.classList.remove('show');
  };

  // 배경 클릭 시 닫기
  confirmModal.onclick = (e) => {
    if (e.target === confirmModal) confirmModal.classList.remove('show');
  };
}

// 성향 변경 적용(테이블 업데이트)
async function applyCorrection(row, newTendency) {
  if (!row) return;

  const doc_id   = row.getAttribute('data-id');
  const tendMap  = { '긍정': 'positive', '중립': 'neutral', '부정': 'negative' };
  const scoreMap = { '긍정': 85, '중립': 50, '부정': 15 };
  const tendency  = tendMap[newTendency] || 'neutral';
  const tendScore = scoreMap[newTendency] || 50.0;

  try {
    const res = await fetch(BASE_URL + '/correction/apply', {
      method     : 'POST',
      headers    : { 'Content-Type': 'application/json' },
      credentials: 'include',
      body       : JSON.stringify({ doc_id, tendency, tend_score: tendScore })
    });
    const data = await res.json();
    if (!res.ok) throw new Error('보정 실패');

    // UI 업데이트
    row.cells[3].innerHTML = `<span class="log-badge ${getTendencyClass(newTendency)}">${newTendency}</span>`;
    row.setAttribute('data-tendency', newTendency);
    row.cells[2].innerHTML = tendScore.toFixed(1);
    row.cells[2].style.color = getScoreColor(tendScore.toFixed(1));
    row.setAttribute('data-score', tendScore.toFixed(1));

    showToast(`✅ ${row.getAttribute('data-title')} → ${newTendency}로 변경되었습니다.`);
  } catch(e) {
    showToast(`❌ 보정 실패: ${e.message}`);
  }
}

// 삭제 확인 모달 열기
function openDeleteConfirmModal() {
  const modal = document.getElementById('deleteConfirmModal');
  if (!modal) return;

  document.getElementById('deleteItemTitle').innerText = currentCorrectionItem.title;

  const confirmBtn = document.getElementById('deleteConfirmOk');
  const newConfirmBtn = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
  newConfirmBtn.onclick = async () => {
    try {
      const res = await fetch(BASE_URL + `/correction/article/${currentCorrectionItem.id}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      const data = await res.json();
      if (!res.ok || data.success === false) throw new Error(data.message || '삭제 실패');
      if (currentCorrectionRow) currentCorrectionRow.remove();
      modal.classList.remove('show');
      showToast(`✅ ${currentCorrectionItem.title} 항목이 삭제되었습니다.`);
      currentCorrectionItem = null;
      currentCorrectionRow = null;
    } catch(e) {
      showToast(`❌ 삭제 실패: ${e.message}`);
    }
  };

  const cancelBtn = document.getElementById('deleteConfirmCancel');
  const newCancelBtn = cancelBtn.cloneNode(true);
  cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
  newCancelBtn.onclick = () => {
    modal.classList.remove('show');
  };

  modal.classList.add('show');
}

// ── 데이터 보정 페이지 (검토 필요 항목 테이블, 수정 버튼)
async function _renderCorrectionPage() {
  const main = document.getElementById('admMain');

  main.innerHTML = `<div style="padding:40px;text-align:center;color:var(--sub);"><i class="fas fa-spinner fa-spin"></i> 불러오는 중...</div>`;

  // 실제 API 호출 — GET /correction/detect
  let reviewItems = [];
  try {
    const res = await fetch(BASE_URL + '/correction/detect', {
      method: 'GET',
      credentials: 'include',
    });
    const data = await res.json();
    const docs = (data.data || data).docs || [];
    reviewItems = docs.map(d => ({
      id      : d.doc_id,
      title   : d.title,
      url     : d.url || '-',
      score: d.tend_score.toFixed(4),
      tendency: d.tendency === 'positive' ? '긍정' : d.tendency === 'negative' ? '부정' : '중립',
    }));
  } catch(e) { console.warn('correction detect 실패:', e); }

  main.innerHTML = `
    <div class="page-title">
      <i class="fas fa-wand-magic-sparkles"></i> 데이터 보정 (비정형 성향치)
    </div>
    <div class="adm-stats-grid">
      <div class="adm-stat-card asc-warn"><div class="asc-label">감지건수</div><div class="asc-val">${reviewItems.length}</div><div class="asc-sub">비정형 감지</div></div>
      <div class="adm-stat-card asc-ok"><div class="asc-label">자동보정</div><div class="asc-val">-</div><div class="asc-sub">자동 처리됨</div></div>
      <div class="adm-stat-card asc-err"><div class="asc-label">검토필요</div><div class="asc-val">${reviewItems.length}</div><div class="asc-sub">관리자 확인 필요</div></div>
      <div class="adm-stat-card asc-info"><div class="asc-label">학습데이터 누적</div><div class="asc-val">-</div><div class="asc-sub">재학습 대기</div></div>
    </div>
    <div class="adm-log-wrap">
      <div class="adm-log-toolbar">
        <div class="alt-title"><i class="fas fa-triangle-exclamation" style="color:var(--gold);"></i> 검토 필요 항목</div>
        <div class="alt-actions">
          <button class="adm-btn adm-btn-ghost" id="refreshCorrectionBtn"><i class="fas fa-rotate-right"></i> 새로고침</button>
        </div>
      </div>
      <div style="overflow-x:auto;">
        <table class="adm-table" id="correctionTable">
          <thead><tr><th>제목</th><th style="width:40%">URL</th><th>tend_score</th><th>tendency</th><th style="width:100px">처리</th></tr></thead>
          <tbody id="correctionTableBody">
            ${reviewItems.map(item => `
              <tr data-id="${item.id}" data-title="${item.title.replace(/"/g, '&quot;')}" data-url="${item.url}" data-score="${item.score}" data-tendency="${item.tendency}">
                <td><strong>${item.title}</strong></td>
                <td class="log-msg">${item.url}</td>
                <td style="color:${getScoreColor(item.score)}; font-weight:800;">${item.score}</td>
                <td><span class="log-badge ${getTendencyClass(item.tendency)}">${item.tendency}</span></td>
                <td><button class="adm-btn adm-btn-primary edit-correction-btn" data-id="${item.id}" style="font-size:12px; padding:6px 14px;"><i class="fas fa-pen"></i> 수정</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  document.querySelectorAll('.edit-correction-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const row = btn.closest('tr');
      const id = btn.getAttribute('data-id');
      const title = row.getAttribute('data-title');
      const url = row.getAttribute('data-url');
      const score = row.getAttribute('data-score');
      const currentTendency = row.getAttribute('data-tendency');
      currentCorrectionItem = { id, title, url, score, currentTendency };
      currentCorrectionRow = row;
      openConfirmCorrectionModal();
    });
  });

  const refreshBtn = document.getElementById('refreshCorrectionBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => { _renderCorrectionPage(); });
  }
}
// 사이드바 버튼 클릭 시 해당 렌더 함수 호출
function _admRoute(page){
  if(_tailInterval){ clearInterval(_tailInterval); _tailInterval=null; }
  document.querySelectorAll('.adm-nav-btn').forEach(b=>b.classList.toggle('active', b.dataset.admPage===page));
  sessionStorage.setItem('admCurrentPage', page);
  switch(page){
    case 'logs':       _renderLogPage(page); break;
    case 'crawler':    _renderCrawlerPage(); break;
    case 'es':         _renderEsPage(); break;
    case 'correction': _renderCorrectionPage(); break;
    default:           _renderLogPage(page);
  }
}

// 초기화: 로그 뷰어 로드, 네비게이션 이벤트, 모달 닫기
function initAdminScreen() {
  _fetchAdminLogs().then(logs => {
    _admLogs = logs;
    const savedPage = sessionStorage.getItem('admCurrentPage') || 'logs';
    _admRoute(savedPage);
  }).catch(() => {
    _admLogs = [];
    _admRoute('logs');
  });

  document.querySelectorAll('.adm-nav-btn').forEach(btn => {
    btn.addEventListener('click', () => _admRoute(btn.dataset.admPage));
  });

  document.getElementById('admLogoutBtn').addEventListener('click', async () => {
  if (_tailInterval) { clearInterval(_tailInterval); _tailInterval = null; }
  try {
    await fetch(BASE_URL + '/admin/logout', { method: 'POST', credentials: 'include' });
    await fetch(BASE_URL + '/membership/logout', { method: 'POST', credentials: 'include' });
  } catch(e) {}
  localStorage.removeItem('fp_session');
  sessionStorage.removeItem('fp_session');
  sessionStorage.removeItem('admCurrentPage');
  location.replace('login.html');
});

  // ========== 모달 배경 클릭 시 닫기 ==========
  
  // confirmCorrectionModal 닫기 (배경 클릭 시)
  const confirmModal = document.getElementById('confirmCorrectionModal');
  if (confirmModal) {
    confirmModal.addEventListener('click', (e) => {
      if (e.target === confirmModal) {
        confirmModal.classList.remove('show');
      }
    });
  }
  
  // deleteConfirmModal 닫기 (배경 클릭 시)
  const deleteModal = document.getElementById('deleteConfirmModal');
  if (deleteModal) {
    deleteModal.addEventListener('click', (e) => {
      if (e.target === deleteModal) {
        deleteModal.classList.remove('show');
      }
    });
  }
  
  // errorRetryModal 닫기 (배경 클릭 시)
  const errorModal = document.getElementById('errorRetryModal');
  if (errorModal) {
    errorModal.addEventListener('click', (e) => {
      if (e.target === errorModal) {
        errorModal.style.display = 'none';
      }
    });
  }
}

// 오류 재시도 모달
function openErrorRetryModal() {
  document.getElementById('errorRetryModal').style.display = 'flex';
}

// DOMContentLoaded 이벤트 (errorRetryModal 닫기 버튼)
document.addEventListener('DOMContentLoaded', () => {
  const closeBtn = document.getElementById('closeErrorRetryModal');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      document.getElementById('errorRetryModal').style.display = 'none';
    });
  }
});
/**
 * 누락 URL 재시도
 * @param {HTMLButtonElement} btn - 클릭된 버튼
 * @param {string} url - 재시도할 URL
 * @param {string} title - 기사 제목
 * @param {string} country - 국가 코드 (KR/US)
 * @param {HTMLElement} statusCell - 상태 표시 셀
 */

// 개별 URL 재시도 (ES페이지)
async function retryMissingUrl(btn, url, title, country, statusCell) {
  // 1. 버튼 비활성화 및 텍스트 변경
  const originalText = btn.innerText;
  btn.disabled = true;
  btn.innerText = '처리 중...';
  
  // 2. 상태 표시 변경 (재시도 중)
  statusCell.innerHTML = `<span class="log-badge log-warn">재시도 중</span>`;
  
  try {
    // 3. 백엔드 API 호출 (실제 구현 시 URL 수정)
    const response = await fetch('/api/retry-missing', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, title, country })
    });
    const result = await response.json();
    
    if (response.ok && result.success) {
      // 성공 시
      statusCell.innerHTML = `<span class="log-badge log-success">복구 완료</span>`;
      btn.innerText = '완료';
      btn.disabled = true; // 계속 비활성화
      showToast(`✅ 복구 성공: ${title}`);
    } else {
      // 실패 시
      statusCell.innerHTML = `<span class="log-badge log-error">재시도 실패</span>`;
      btn.innerText = originalText; // '재시도'로 복구
      btn.disabled = false;
      showToast(`❌ 복구 실패: ${result.message || '알 수 없는 오류'}`);
    }
  } catch (err) {
    console.error(err);
    statusCell.innerHTML = `<span class="log-badge log-error">네트워크 오류</span>`;
    btn.innerText = originalText;
    btn.disabled = false;
    showToast(`❌ 네트워크 오류: ${err.message}`);
  }
}