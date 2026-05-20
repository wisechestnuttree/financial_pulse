// admin.js
// ── 누락된 상수 정의
const ADM_SUBJECTS = ['전체','크롤링','데이터관리','비정형수치','로그인'];
const ADM_LEVELS   = ['ALL','INFO','WARN','ERROR','DEBUG','SUCCESS'];

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

let _admLogs = _genLogs(120);
let _tailInterval = null;

// ── 레벨별 뱃지 HTML생성
function _lvlBadge(lvl){
  const m={'INFO':'log-info','WARN':'log-warn','ERROR':'log-error','DEBUG':'log-debug','SUCCESS':'log-success'};
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
  const byLevel = {INFO:0,WARN:0,ERROR:0,DEBUG:0,SUCCESS:0};
  logs.forEach(l=>{ if(byLevel[l.level]!==undefined) byLevel[l.level]++; });
  return {total, ...byLevel};
}

// ── 로그 뷰어 페이지 (탭, 필터 바, 통계 카드, 로그 테이블)
function _renderLogPage(page){
  const main = document.getElementById('admMain');
  const esLabel = {'전체':'전체 ES','크롤링':'크롤링 ES','데이터관리':'데이터관리 ES','비정형수치':'비정형수치 ES','로그인':'로그인 ES'};

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
          <thead><tr><th style="width:44px;"></th><th>타임스탬프</th><th>주체</th><th>레벨</th><th>메시지</th></tr></thead>
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
      <div class="adm-stat-card asc-warn"><div class="asc-label">WARN</div><div class="asc-val">${s.WARN}</div><div class="asc-sub">모니터링 필요</div></div>
      <div class="adm-stat-card asc-ok"><div class="asc-label">SUCCESS</div><div class="asc-val">${s.SUCCESS}</div><div class="asc-sub">정상 완료</div></div>
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

  function _doFilter(){
    const level   = document.getElementById('admLevelFilter').value;
    const subject = curEs==='전체' ? document.getElementById('admSubjectFilter').value : curEs;
    const kw      = document.getElementById('admKeyword').value.trim();
    const from    = document.getElementById('admFromFilter').value.replace('T',' ');
    const to      = document.getElementById('admToFilter').value.replace('T',' ');
    _renderTable(_filterLogs(_admLogs, level, subject, kw, from||null, to||null));
  }

  document.getElementById('admEsTabs').addEventListener('click', e=>{
    const btn = e.target.closest('.adm-tab');
    if(!btn) return;
    document.querySelectorAll('.adm-tab').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    curEs = btn.dataset.es;
    document.getElementById('admSubjectFilter').value = curEs;
    _doFilter();
  });

  document.getElementById('admSearchBtn').addEventListener('click', _doFilter);
  document.getElementById('admResetBtn').addEventListener('click', ()=>{
    ['admLevelFilter','admSubjectFilter'].forEach(id=>document.getElementById(id).value=id.includes('Level')?'ALL':'전체');
    ['admKeyword','admFromFilter','admToFilter'].forEach(id=>document.getElementById(id).value='');
    curEs='전체';
    document.querySelectorAll('.adm-tab').forEach((b,i)=>{b.classList.toggle('active',i===0);});
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
function _renderCrawlerPage() {
  const main = document.getElementById('admMain');
  const crawlLogs = _filterLogs(_admLogs, 'ALL', '크롤링', '', '', '');
  const stats = _calcStats(crawlLogs);
  
  main.innerHTML = `
    <h2 style="font-size:20px;font-weight:900;color:var(--navy);display:flex;align-items:center;gap:10px;">
      <i class="fas fa-spider" style="color:var(--teal);"></i> 크롤링 스케줄러 관리
    </h2>
    <div class="adm-stats-grid">
      <div class="adm-stat-card asc-info"><div class="asc-label">총 로그</div><div class="asc-val">${stats.total}</div></div>
      <div class="adm-stat-card asc-err"><div class="asc-label">ERROR</div><div class="asc-val">${stats.ERROR}</div><div class="asc-sub">재시도 대상</div></div>
      <div class="adm-stat-card asc-warn"><div class="asc-label">WARN</div><div class="asc-val">${stats.WARN}</div></div>
      <div class="adm-stat-card asc-ok"><div class="asc-label">마지막 실행</div><div class="asc-val" style="font-size:16px;">04:00</div><div class="asc-sub">오늘 정상완료</div></div>
    </div>
    <div class="adm-log-wrap">
      <div class="adm-log-toolbar">
        <div class="alt-title"><i class="fas fa-spider" style="color:var(--teal);"></i> 크롤링 로그 (오류 우선)</div>
        <div class="alt-actions">
          <button class="adm-btn adm-btn-primary" id="openErrorRetryBtn"><i class="fas fa-rotate-right"></i> 오류 재시도</button>
        </div>
      </div>
      <div style="overflow-x:auto;">
        <table class="adm-table">
          <thead>
            <tr><th></th><th>타임스탬프</th><th>레벨</th><th>메시지</th></tr>
          </thead>
          <tbody>
            ${crawlLogs.filter(l => l.level === 'ERROR' || l.level === 'WARN').slice(0, 50).map(l => `
              <tr>
                <td style="white-space:nowrap;font-family:monospace;font-size:11.5px;">${l.timestamp}</td>
                <td>${_lvlBadge(l.level)}</td>
                <td class="log-msg">${l.message}</td>
              </tr>
            `).join('')}
          </tbody>
        <table>
      </div>
    </div>
  `;
  
  const retryBtn = document.getElementById('openErrorRetryBtn');
  if (retryBtn) {
    retryBtn.addEventListener('click', openErrorRetryModal);
  }
}

// ES 인덱스 관리: 인덱스 현황, 누락 URL 목록, 재수집 버튼
function _renderEsPage(){
  const main = document.getElementById('admMain');

  // 누락 URL 데이터 (필요에 따라 배열에 추가)
  const missingUrls = [
    { url: "https://n.news.naver.com/article/055/0001234567", title: "원달러 환율 급등", country: "KR", status: "404", statusClass: "log-error" },
    { url: "https://n.news.naver.com/article/030/0009999999", title: "코스닥 급락", country: "KR", status: "대기", statusClass: "log-warn" }
  ];

  // 누락 URL 목록 테이블의 행 HTML 동적 생성
  const missingRowsHtml = missingUrls.map(item => `
    <tr data-url="${item.url}" data-title="${item.title.replace(/"/g, '&quot;')}" data-country="${item.country}">
      <td class="log-msg" style="word-break: break-all;">${item.url}</td>
      <td>${item.title}</td>
      <td>${item.country}</td>
      <td class="status-cell"><span class="log-badge ${item.statusClass}">${item.status}</span></td>
      <td><button class="adm-btn adm-btn-ghost retry-missing-btn" style="font-size:11px;">재시도</button></td>
    </tr>
  `).join('');

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
            <tr>
              <td><strong>newsStorage</strong></td>
              <td>284,320</td>
              <td>312</td>
              <td>308</td>
              <td style="color:var(--neg);font-weight:800;">4</td>
              <td><span class="log-badge log-warn">누락감지</span></td>
              <td><button class="adm-btn adm-btn-primary recollect-btn" data-index="newsStorage" data-missing="4" style="font-size:11px;">재수집</button></td>
            </tr>
            <tr>
              <td><strong>crawlLogs</strong></td>
              <td>48,200</td>
              <td>-</td>
              <td>-</td>
              <td>0</td>
              <td><span class="log-badge log-success">정상</span></td>
              <td></td>
            </tr>
            <tr>
              <td><strong>dataLogs</strong></td>
              <td>24,100</td>
              <td>-</td>
              <td>-</td>
              <td>0</td>
              <td><span class="log-badge log-success">정상</span></td>
              <td></td>
            </tr>
            <tr>
              <td><strong>mlLogs</strong></td>
              <td>7,280</td>
              <td>-</td>
              <td>-</td>
              <td>0</td>
              <td><span class="log-badge log-success">정상</span></td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
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
          <tbody id="missingUrlTableBody">
            ${missingRowsHtml}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // 인덱스 재수집 버튼 이벤트 (기존과 동일)
  document.querySelectorAll('.recollect-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const missingCount = btn.getAttribute('data-missing') || '0';
      const indexName = btn.getAttribute('data-index');
      showRecollectConfirmModal(missingCount, indexName);
    });
  });

  // 개별 URL 재시도 버튼 이벤트 (동적으로 생성된 모든 버튼에 대해)
  document.querySelectorAll('.retry-missing-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const row = btn.closest('tr');
      const url = row.getAttribute('data-url');
      const title = row.getAttribute('data-title');
      const country = row.getAttribute('data-country');
      const statusCell = row.querySelector('.status-cell');
      await retryMissingUrl(btn, url, title, country, statusCell);
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
function applyCorrection(row, newTendency) {
  if (!row) return;
  const tendencyCell = row.cells[3];
  tendencyCell.innerHTML = `<span class="log-badge ${getTendencyClass(newTendency)}">${newTendency}</span>`;
  row.setAttribute('data-tendency', newTendency);

  // 점수 랜덤 조정 (긍정 75~95, 중립 40~60, 부정 5~25)
  let newScore = '50.0';
  if (newTendency === '긍정') newScore = (Math.random() * 20 + 75).toFixed(1);
  else if (newTendency === '부정') newScore = (Math.random() * 20 + 5).toFixed(1);
  else if (newTendency === '중립') newScore = (Math.random() * 20 + 40).toFixed(1);

  const scoreCell = row.cells[2];
  scoreCell.innerHTML = newScore;
  scoreCell.style.color = getScoreColor(newScore);
  row.setAttribute('data-score', newScore);

  showToast(`${row.getAttribute('data-title')} → ${newTendency}로 변경되었습니다.`);
}

// 삭제 확인 모달 열기
function openDeleteConfirmModal() {
  const modal = document.getElementById('deleteConfirmModal');
  if (!modal) return;
  
  document.getElementById('deleteItemTitle').innerText = currentCorrectionItem.title;
  
  const confirmBtn = document.getElementById('deleteConfirmOk');
  const newConfirmBtn = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
  newConfirmBtn.onclick = () => {
    if (currentCorrectionRow) currentCorrectionRow.remove();
    modal.classList.remove('show');
    showToast(`${currentCorrectionItem.title} 항목이 삭제되었습니다.`);
    currentCorrectionItem = null;
    currentCorrectionRow = null;
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
function _renderCorrectionPage() {
  const main = document.getElementById('admMain');
  
  const reviewItems = [
    { id: 1, title: "반도체 급등 이유는?", url: "https://n.news.naver.com/article/082/0001234567", score: "98.7", tendency: "매우긍정" },
    { id: 2, title: "AI 주가 폭락 우려", url: "https://n.news.naver.com/article/082/0009876543", score: "2.1", tendency: "매우부정" },
    { id: 3, title: "금리 인하 가능성", url: "https://n.news.naver.com/article/082/0005555555", score: "65.4", tendency: "중립" },
    { id: 4, title: "2차전지 특허 분쟁", url: "https://n.news.naver.com/article/082/0001111111", score: "82.3", tendency: "긍정" },
    { id: 5, title: "환율 급등 영향", url: "https://n.news.naver.com/article/082/0002222222", score: "23.7", tendency: "부정" }
  ];

  main.innerHTML = `
    <div class="page-title">
      <i class="fas fa-wand-magic-sparkles"></i> 데이터 보정 (비정형 성향치)
    </div>
    <div class="adm-stats-grid">
      <div class="adm-stat-card asc-warn"><div class="asc-label">감지건수</div><div class="asc-val">${reviewItems.length}</div><div class="asc-sub">오늘 03:00 배치</div></div>
      <div class="adm-stat-card asc-ok"><div class="asc-label">자동보정</div><div class="asc-val">4</div><div class="asc-sub">자동 처리됨</div></div>
      <div class="adm-stat-card asc-err"><div class="asc-label">검토필요</div><div class="asc-val">${reviewItems.length}</div><div class="asc-sub">관리자 확인 필요</div></div>
      <div class="adm-stat-card asc-info"><div class="asc-label">학습데이터 누적</div><div class="asc-val">1,284</div><div class="asc-sub">재학습 대기</div></div>
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
    btn.addEventListener('click', (e) => {
      const row = btn.closest('tr');
      const id = parseInt(btn.getAttribute('data-id'));
      const title = row.getAttribute('data-title');
      const url = row.getAttribute('data-url');
      const score = row.getAttribute('data-score');
      const currentTendency = row.getAttribute('data-tendency');
      
      currentCorrectionItem = { id, title, url, score, currentTendency };
      currentCorrectionRow = row;
      
      openConfirmCorrectionModal();  // 성향 변경 모달 (긍정/중립/부정 선택)
    });
  });
  
  const refreshBtn = document.getElementById('refreshCorrectionBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => { location.reload(); });
  }
}

// 사이드바 버튼 클릭 시 해당 렌더 함수 호출
function _admRoute(page){
  if(_tailInterval){ clearInterval(_tailInterval); _tailInterval=null; }
  document.querySelectorAll('.adm-nav-btn').forEach(b=>b.classList.toggle('active', b.dataset.admPage===page));
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
  _admLogs = _genLogs(120);
  _admRoute('logs');
  
  document.querySelectorAll('.adm-nav-btn').forEach(btn => {
    btn.addEventListener('click', () => _admRoute(btn.dataset.admPage));
  });
  
  document.getElementById('admLogoutBtn').addEventListener('click', () => {
    if (_tailInterval) { clearInterval(_tailInterval); _tailInterval = null; }
    localStorage.removeItem('fp_session');
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