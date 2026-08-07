# -*- coding: utf-8 -*-
""" 프로젝트 진척 대시보드 - 성능·안정성·목표대비 진척을 한 장으로 (매일 백테스팅 직후 자동 실행)

    보여주는 것
      1. 한눈에   - 백테 계좌, 홀드아웃 누적, 1차 판정선까지 남은 거리, 당일 성적
      2. 성능     - 개발표본 vs 홀드아웃, 구간1/구간2 분해, 최근 추이
      3. 안정성   - 손실일 비율, 최대낙폭, 하루빼기 최악, 팻테일 의존도, 통계 유의성, 실매매 괴리
      4. 진척     - 판정선(홀드아웃 15일 / 90건 / 180건, 롤링 재검증 24거래일) 대비 진행률
      5. 앞으로   - 최근 거래속도로 환산한 남은 거래일과 예상 도달일

    판정선 근거는 2026-08-04 표본요구량 계산(관측분포 부트스트랩, 양측 95%·검정력 80%):
      거래당 참 기대값 +0.90% 가정 → 90건 / +0.64% 가정 → 180건.
    ※ 이 도구는 읽기 전용이다. 백테 산출물을 만들지도 고치지도 않는다.
    ※ 카카오 발송에는 일절 관여하지 않는다 (텔레그램만 사용).

    사용:
        python analyzer/대시보드.py              # 리포트 생성 + 텔레그램 발송
        python analyzer/대시보드.py --no-send     # 생성만 (발송 안 함)
"""
import glob
import json
import os
import re
import sys
import unicodedata
import urllib.parse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ut

# ===== 판정 기준 (근거 없이 바꾸지 말 것) =====
S_개발표본_종료 = '20260724'      # 이 날짜까지가 로직 개발에 쓰인 표본
N_계좌_시작 = 10_000_000          # 백테 계좌 시작 자본
N_목표_홀드일 = 15                # 구간1 홀드아웃 1차 판정선 (일)
N_목표_건수1 = 90                 # 거래당 기대값 +0.90% 가정 시 판정 가능 건수
N_목표_건수2 = 180                # 거래당 기대값 +0.64% 가정 시 판정 가능 건수
N_목표_롤링창 = 10                # 롤링 walk-forward 학습창 (일)
N_목표_롤링폴드 = 27              # 그 창에서 참 차이 +1.0%p/일 을 잡는 데 필요한 폴드 수
N_목표_롤링일 = N_목표_롤링창 + N_목표_롤링폴드   # 총 필요 거래일 (창을 채운 뒤부터 폴드가 생긴다)
S_리포트폴더 = '클로드분석결과'      # 서버 웹폴더(server_kakao) 하위 폴더명

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2128;--bd:#30363d;--tx:#c9d1d9;--mu:#8b949e;
--up:#ff7b72;--dn:#58a6ff;--ok:#3fb950;--wn:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
line-height:1.7;font-size:15px;}
.wrap{max-width:1180px;margin:0 auto;padding:40px 24px 80px;}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.4px;}
h2{font-size:21px;margin:52px 0 14px;padding-bottom:10px;border-bottom:1px solid var(--bd);}
h3{font-size:16px;margin:26px 0 8px;color:#e6edf3;}
.sub{color:var(--mu);font-size:14px;margin-bottom:8px;}
p{margin:10px 0;}
.lead{background:var(--panel);border:1px solid var(--bd);border-left:3px solid var(--wn);
border-radius:6px;padding:16px 20px;margin:22px 0;}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:18px 0;}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0;}
@media (max-width:900px){.grid4{grid-template-columns:repeat(2,1fr);}}
@media (max-width:520px){.grid4{grid-template-columns:1fr;}}
.rowlbl{color:var(--mu);font-size:12px;letter-spacing:.4px;margin:20px 0 2px;
text-transform:uppercase;}
.card{background:var(--panel);border:1px solid var(--bd);border-radius:6px;padding:16px 18px;}
.card .k{color:var(--mu);font-size:12.5px;margin-bottom:6px;}
.card .v{font-size:25px;font-weight:600;letter-spacing:-.5px;}
.card .n{color:var(--mu);font-size:12px;margin-top:4px;}
.tw{overflow-x:auto;margin:16px 0;-webkit-overflow-scrolling:touch;}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:520px;}
th,td{border:1px solid var(--bd);padding:8px 11px;text-align:right;white-space:nowrap;}
th{background:var(--panel2);color:#e6edf3;font-weight:600;text-align:center;}
td.l,th.l{text-align:left;} td.c{text-align:center;}
tbody tr:nth-child(odd){background:rgba(255,255,255,.017);}
tr.sum td{border-top:2px solid var(--bd);font-weight:600;background:var(--panel2);}
.up{color:var(--up);} .dn{color:var(--dn);} .mu{color:var(--mu);}
.ok{color:var(--ok);font-weight:600;} .wn{color:var(--wn);}
.pie{text-align:center;padding:16px 14px 14px;}
.pie .t{color:#e6edf3;font-size:13.5px;font-weight:600;}
.pie svg{width:124px;height:124px;display:block;margin:8px auto 0;}
.pie .pv{font-size:25px;font-weight:600;fill:#e6edf3;}
.pie .pn{font-size:11.5px;fill:var(--mu);}
.pie .s{font-size:12.5px;margin-top:4px;color:var(--tx);}
.pie .m{color:var(--mu);font-size:11.5px;margin-top:3px;line-height:1.5;}
ul{margin:10px 0;padding-left:20px;} li{margin:6px 0;}
.ft{margin-top:60px;padding-top:18px;border-top:1px solid var(--bd);color:var(--mu);font-size:12.5px;}
.note{color:var(--mu);font-size:13px;margin:8px 0;}
code{background:var(--panel2);border:1px solid var(--bd);border-radius:4px;
padding:1px 6px;font-size:12.5px;color:#e6edf3;}
"""


def s_pct(v, n=2, s_단위='%'):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return '<span class="mu">-</span>'
    c = 'up' if v > 0 else ('dn' if v < 0 else 'mu')
    return f'<span class="{c}">{v:+.{n}f}{s_단위}</span>'


# 텔레그램 고정폭 블록 줄맞춤
#   텔레그램의 고정폭 글꼴에는 한글이 없어 시스템 글꼴로 대체되고, 그 한글 폭은 영문의 정확히 2배가 아니다.
#   그래서 '한글=2칸'으로 계산해 공백을 채우면 줄이 어긋난다(2026-08-04 실제 화면에서 확인).
#   해법: 라벨은 전각(한글·전각공백 U+3000)만, 값은 ASCII만 쓰고 각각 글자 수를 고정한다.
#         그러면 한글과 영문의 폭 비율이 얼마이든 두 칸의 폭이 줄마다 같아져 항상 맞는다.
#   ※ 전각으로 통일하면 <code> 없이도 맞고 글자도 커지지만, 숫자 모양이 낯설어 원래 크기로 되돌렸다.
S_전각공백 = '　'
N_라벨_전각 = 7        # 라벨 칸 (전각 글자 수)
N_값_ASCII = 10       # 값 칸 (ASCII 글자 수)


def s_행(s_라벨, s_값):
    """ 라벨(전각 고정) + 값(ASCII 우측정렬 고정) """
    s_l = str(s_라벨).replace(' ', S_전각공백)
    s_l += S_전각공백 * max(0, N_라벨_전각 - len(s_l))
    return f'{s_l}{str(s_값).rjust(N_값_ASCII)}'


def b_전각만(s):
    """ 라벨에 ASCII가 섞이지 않았는지 확인 (섞이면 줄맞춤이 깨진다) """
    return all(unicodedata.east_asian_width(c) in ('W', 'F') for c in str(s))


def s_도넛(s_제목, n_현재, n_목표, s_단위='', s_비고=''):
    """ 진행률 도넛 (외부 라이브러리 없이 SVG 원호로 그린다) """
    n_율 = min(100.0, n_현재 / n_목표 * 100) if n_목표 else 0.0
    n_둘레 = 2 * np.pi * 52
    n_호 = n_둘레 * n_율 / 100
    n_남음 = max(0, n_목표 - n_현재)
    return f"""<div class="card pie">
<div class="t">{s_제목}</div>
<svg viewBox="0 0 120 120" role="img" aria-label="{s_제목} {n_율:.0f}%">
<circle cx="60" cy="60" r="52" fill="none" stroke="#21262d" stroke-width="13"/>
<circle cx="60" cy="60" r="52" fill="none" stroke="#388bfd" stroke-width="13"
 stroke-linecap="round" stroke-dasharray="{n_호:.2f} {n_둘레 - n_호:.2f}"
 transform="rotate(-90 60 60)"/>
<text class="pv" x="60" y="57" text-anchor="middle" dominant-baseline="middle">{n_율:.0f}%</text>
<text class="pn" x="60" y="77" text-anchor="middle">{n_현재:,.0f} / {n_목표:,.0f}{s_단위}</text>
</svg>
<div class="s">{n_남음:,.0f}{s_단위} 남음</div>
<div class="m">{s_비고}</div>
</div>"""


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection
class Dashboard:
    """ 진척 대시보드 생성 및 발송 """

    def __init__(self):
        dic_폴더 = ut.폴더manager.FolderManager().dic_폴더정보
        self.folder_백테 = os.path.join(dic_폴더['분석|백테스팅'], '클로드_틱기반매수세')
        self.folder_거래 = os.path.join(self.folder_백테, '30_거래내역')
        self.folder_결과 = os.path.join(self.folder_백테, '40_결과정리')
        self.folder_주문 = dic_폴더['매수매도|주문체결']

        log = ut.로그maker.LogMaker(s_파일명='대시보드', s_로그명='로그이름_analyzer')
        self.make_로그 = log.make_로그

        # 리포트 저장 폴더·주소 - server_info.json 에서 유도 (코드에 주소를 박지 않는다)
        dic_config = ut.도구manager.ToolManager().config로딩()
        path_서버 = os.path.join(dic_config['folder_설정'], 'server_info.json')
        with open(path_서버, mode='rt', encoding='utf-8') as f:
            dic_서버 = json.load(f)
        self.folder_리포트 = os.path.join(dic_서버['folder']['server_kakao'], S_리포트폴더)
        self.s_웹주소 = (f'http://{dic_서버["sftp"]["hostname"]}/'
                     f'{os.path.basename(dic_서버["folder"]["server_kakao"])}/{S_리포트폴더}')

    # =================================================================
    # 자료 수집
    # =================================================================
    def df_거래(self):
        """ 30_거래내역 전량 (일자·구간·수익률) """
        li = list()
        for path in sorted(glob.glob(os.path.join(self.folder_거래, 'df_거래내역_*.pkl'))):
            df = pd.read_pickle(path)
            if len(df):
                li.append(df[['일자', '종목코드', '종목명', '수익률', '구간']])
        return pd.concat(li, ignore_index=True) if li else pd.DataFrame()

    def df_결과(self):
        """ 40_결과정리 최신본 (일자별 계좌잔고) """
        li = sorted(glob.glob(os.path.join(self.folder_결과, 'df_결과정리_*.pkl')))
        return pd.read_pickle(li[-1]) if li else pd.DataFrame()

    def df_실매매(self):
        """ 주문체결 원장 → 일자·종목별 실현 수익률 (비용 후) """
        li = list()
        for path in sorted(glob.glob(os.path.join(self.folder_주문, '주문체결_*.csv'))):
            s_일자 = re.findall(r'\d{8}', os.path.basename(path))[0]
            try:
                d = pd.read_csv(path, encoding='cp949', dtype=str, on_bad_lines='skip')
            except (OSError, UnicodeDecodeError, pd.errors.ParserError):
                continue
            d = d[d['주문상태'] == '체결']
            if not len(d):
                continue

            # 체결누계금액·체결량·수수료·세금은 주문번호 단위 누계값 - 주문번호별 마지막 행만 합산
            def n_누계(g, s_컬럼):
                n = 0
                for _, gg in g.groupby('주문번호', sort=False):
                    n += pd.to_numeric(gg[s_컬럼], errors='coerce').fillna(0).iloc[-1]
                return float(n)

            for s_종목, g in d.groupby('종목코드'):
                g매수, g매도 = g[g['매도수구분'] == '매수'], g[g['매도수구분'] == '매도']
                if not len(g매수) or not len(g매도):
                    continue
                n_매수금, n_매도금 = n_누계(g매수, '체결누계금액'), n_누계(g매도, '체결누계금액')
                if n_매수금 <= 0:
                    continue
                n_비용 = n_누계(g, '당일매매수수료') + n_누계(g, '당일매매세금')
                li.append(dict(일자=s_일자, 종목코드=s_종목,
                               순손익=n_매도금 - n_매수금 - n_비용, 매수금=n_매수금,
                               수익률=(n_매도금 - n_매수금 - n_비용) / n_매수금 * 100))
        return pd.DataFrame(li)

    # =================================================================
    # 지표 계산
    # =================================================================
    @staticmethod
    def dic_집계(df):
        r = df['수익률'].values
        if not len(r):
            return dict(일수=0, 건수=0, 합계=0.0, 거래당=np.nan, 승률=np.nan,
                        최대=np.nan, 최소=np.nan, 손실일=0)
        sri_일 = df.groupby('일자')['수익률'].sum()
        return dict(일수=int(df['일자'].nunique()), 건수=len(r), 합계=float(r.sum()),
                    거래당=float(r.mean()), 승률=float((r > 0).mean() * 100),
                    최대=float(r.max()), 최소=float(r.min()),
                    손실일=int((sri_일 < 0).sum()))

    @staticmethod
    def n_loo(df):
        """ 하루빼기 최악 - 가장 좋은 하루를 빼도 합계가 남는가 """
        sri = df.groupby('일자')['수익률'].sum()
        return float(sri.sum() - sri.max()) if len(sri) else np.nan

    @staticmethod
    def n_t값(df):
        r = df['수익률'].values
        if len(r) < 3 or r.std(ddof=1) == 0:
            return np.nan
        return float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r))))

    @staticmethod
    def n_팻테일(df):
        """ 상위 3건이 총이익에서 차지하는 비중 % """
        r = df['수익률'].values
        n_익 = r[r > 0].sum()
        return float(np.sort(r)[-3:].sum() / n_익 * 100) if n_익 > 0 else np.nan

    @staticmethod
    def n_낙폭(df_결과):
        """ 계좌 잔고 기준 최대 낙폭 % """
        if not len(df_결과) or '거래후예수금' not in df_결과:
            return np.nan
        ary = pd.to_numeric(df_결과['거래후예수금'], errors='coerce').ffill().values
        ary = np.concatenate(([N_계좌_시작], ary))
        return float(((ary - np.maximum.accumulate(ary)) / np.maximum.accumulate(ary)).min() * 100)

    # =================================================================
    # 리포트 생성
    # =================================================================
    def li_롤링비교(self):
        """ 파라미터 고정(현행) vs 매일 직전 N일 재최적화(튜닝) 비교 구획

            analyzer/롤링워크포워드.py 가 손익행렬을 캐시에 쌓고 새 일자만 증분 계산한다.
            무거운 계산이므로 실패하면 조용히 건너뛴다 — 대시보드 본체를 막지 않는다. """
        try:
            from analyzer.롤링워크포워드 import 롤링워크포워드, N_학습창
            wf = 롤링워크포워드()
            dic_r = wf.평가(n_학습창=N_학습창)
        except Exception as e:                                  # noqa: BLE001
            self.make_로그(f'롤링 비교 생략 - {type(e).__name__}: {e}')
            return list()
        if not dic_r:
            return list()

        B = ['<h2>파라미터 고정 vs 매일 재최적화</h2>']
        B.append(f'<p class="mu">직전 {dic_r["학습창"]}거래일로 진입 조건 '
                 f'{dic_r["조합수"]}칸을 훑어 최적을 고르고, 그 값을 <b>다음 미지의 1일</b>에 '
                 f'적용했다면 어땠는지. 청산·구간2·자금관리는 전부 현행 그대로이고 '
                 f'구간1 진입 축만 바꾼다. 격자에는 아직 매매에 쓰지 않는 후보지표'
                 f'(체결강도·체결횟수강도·단위매수량 등)가 포함돼 있다.</p>')
        B.append('<div class="tw"><table><thead><tr><th class="l">방식</th><th>폴드</th>'
                 '<th>손익 합</th><th>비고</th></tr></thead><tbody>')
        for s_라벨, n_값, s_설명 in [
                ('현행 (파라미터 고정)', dic_r['현행'], '지금 쓰는 값 그대로'),
                (f'매일 재최적화 (직전 {dic_r["학습창"]}일)', dic_r['튜닝'],
                 f'튜닝 우세 {dic_r["승"]}/{len(dic_r["폴드"])}일 · '
                 f'현행과 같은 값을 고른 날 {dic_r["동일"]}일'),
                ('격자 무작위 (대조군)', dic_r['무작위'],
                 f'{dic_r["조합수"]}칸에서 아무거나 골랐을 때의 평균'),
                ('오라클 (상한)', dic_r['오라클'], '검증일을 미리 알았을 때 — 달성 불가')]:
            B.append(f'<tr><td class="l">{s_라벨}</td>'
                     f'<td>{len(dic_r["폴드"]) if "오라클" not in s_라벨 else ""}</td>'
                     f'<td>{s_pct(n_값)}</td>'
                     f'<td class="l"><span class="mu">{s_설명}</span></td></tr>')
        B.append('</tbody></table></div>')
        B.append(f'<p class="mu">재최적화 결과는 격자 {dic_r["조합수"]}칸 중 '
                 f'<b>상위 {dic_r["튜닝백분위"]:.0f}%</b> 자리다. '
                 f'무작위 평균({s_pct(dic_r["무작위"])})과 견줘야 정보를 쓴 것인지 갈린다 — '
                 f'격자를 훑어 최선을 고르는 과정 자체가 다중비교라 그냥 좋아 보일 수 있다.</p>')

        B.append('<h3>폴드별</h3>')
        B.append('<div class="tw"><table><thead><tr><th>검증일</th><th>재최적화</th>'
                 '<th>현행</th><th>오라클</th><th class="l">그날 채택된 조건</th>'
                 '</tr></thead><tbody>')
        for x in dic_r['폴드'][-10:]:
            B.append(f'<tr><td>{x["검증일"]}</td>'
                     f'<td>{s_pct(x["튜닝"])} <span class="mu">({x["건수"]}건)</span></td>'
                     f'<td>{s_pct(x["현행"])}</td><td>{s_pct(x["오라클"])}</td>'
                     f'<td class="l"><span class="mu">{wf.s_파라미터(x["파라미터"])}</span></td>'
                     f'</tr>')
        B.append('</tbody></table></div>')
        B.append('<p class="mu">이 비교는 <b>참고용</b>이다. 폴드가 아직 적고 학습창이 서로 '
                 '겹쳐 독립 시행이 아니며, 결과가 몇 날의 큰 차이에 기대고 있을 수 있다. '
                 '재최적화가 계속 앞선다면 그때 후보를 <b>사전 등록</b>해 현행과 나란히 '
                 '표본외 기록을 쌓는 것이 다음 단계다.</p>')
        return B

    def make_리포트(self):
        df = self.df_거래()
        if not len(df):
            return None, '거래내역 없음'
        df_결 = self.df_결과()
        df_실 = self.df_실매매()

        s_기준일 = str(df['일자'].max())
        d_개발 = df[df['일자'] <= S_개발표본_종료]
        d_홀드 = df[df['일자'] > S_개발표본_종료]
        d_오늘 = df[df['일자'] == s_기준일]
        dic_개발, dic_홀드, dic_전체 = (self.dic_집계(d_개발), self.dic_집계(d_홀드), self.dic_집계(df))
        dic_오늘 = self.dic_집계(d_오늘)

        # 잔고는 '기준일까지'로 잘라서 본다 - 40_결과정리가 30_거래내역보다 앞서 있어도 날짜가 섞이지 않게
        sri_잔고전체 = pd.Series(dtype=float)
        if len(df_결):
            sri_잔고전체 = pd.Series(
                pd.to_numeric(df_결['거래후예수금'], errors='coerce').values,
                index=df_결['일자'].astype(str).values)
            sri_잔고전체 = sri_잔고전체[sri_잔고전체.index <= s_기준일]
        n_잔고 = float(sri_잔고전체.iloc[-1]) if len(sri_잔고전체) else np.nan
        n_계좌율 = (n_잔고 / N_계좌_시작 - 1) * 100 if n_잔고 == n_잔고 else np.nan

        # 홀드아웃만 떼어낸 계좌 - 홀드아웃 시작 시점에 N_계좌_시작 으로 다시 출발했다면
        # 사이징이 총자본 비례(총자본÷분할수)라 수익률은 자본 규모와 무관하다 → 잔고 비율을 그대로 환산해도 된다
        n_잔고홀드, n_홀드계좌율 = np.nan, np.nan
        if len(sri_잔고전체):
            sri_기준 = sri_잔고전체[sri_잔고전체.index <= S_개발표본_종료]
            n_기준잔고 = float(sri_기준.iloc[-1]) if len(sri_기준) else float(N_계좌_시작)
            if n_기준잔고 > 0 and n_잔고 == n_잔고:
                n_잔고홀드 = N_계좌_시작 * n_잔고 / n_기준잔고
                n_홀드계좌율 = (n_잔고홀드 / N_계좌_시작 - 1) * 100

        # 최근 거래속도 (최근 6영업일) - 남은 기간 환산의 기준
        sri_일건수 = df.groupby('일자').size()
        n_속도 = float(sri_일건수.tail(6).mean())
        n_남은1 = max(0, N_목표_건수1 - dic_홀드['건수'])
        n_남은일1 = int(np.ceil(n_남은1 / n_속도)) if n_속도 > 0 else np.nan
        n_남은2 = max(0, N_목표_건수2 - dic_홀드['건수'])
        n_남은일2 = int(np.ceil(n_남은2 / n_속도)) if n_속도 > 0 else np.nan

        def s_예상일(n_영업일):
            if n_영업일 != n_영업일 or n_영업일 <= 0:
                return '도달'
            dt = pd.bdate_range(pd.Timestamp(s_기준일) + pd.Timedelta(days=1), periods=int(n_영업일))
            return dt[-1].strftime('%Y-%m-%d') + ' 무렵'

        B = list()

        # ── 한눈에
        s_판정 = ('<span class="ok">판정 가능 구간 진입</span>' if dic_홀드['건수'] >= N_목표_건수1
                else f'<span class="wn">표본 축적 중</span>')
        B.append(f"""
<div class="lead">
<b>현재 상태 — {s_판정}.</b>
홀드아웃 {dic_홀드['일수']}일 · {dic_홀드['건수']}건 · 거래손익 합 {dic_홀드['합계']:+.2f}%(거래당 {dic_홀드['거래당']:+.3f}%) ·
<b>계좌로는 {n_홀드계좌율:+.2f}%</b>({N_계좌_시작 / 10000:,.0f}만 → {n_잔고홀드:,.0f}원).
1차 판정선({N_목표_건수1}건)까지 <b>{n_남은1}건</b> 남았고 최근 속도({n_속도:.1f}건/일)로 약
<b>{n_남은일1}거래일</b>({s_예상일(n_남은일1)})이 필요하다.
<b>그 전까지의 숫자는 참고용이며 배포·중단 판단의 근거로 쓰지 않는다.</b>
</div>
""")
        # 당일 지표
        n_승 = round(dic_오늘['건수'] * dic_오늘['승률'] / 100) if dic_오늘['건수'] else 0
        n_오늘1 = float(d_오늘[d_오늘['구간'] == '구간1']['수익률'].sum())
        n_오늘2 = float(d_오늘[d_오늘['구간'] == '구간2']['수익률'].sum())
        n_오늘건1 = int((d_오늘['구간'] == '구간1').sum())
        n_오늘건2 = int((d_오늘['구간'] == '구간2').sum())

        def s_구간요약(s_구간):
            """ '구간1 2건 1승1패' - 거래 없으면 건수만 """
            x = d_오늘[d_오늘['구간'] == s_구간]['수익률']
            if not len(x):
                return f'{s_구간} 0건'
            n_w = int((x > 0).sum())
            return f'{s_구간} {len(x)}건 {n_w}승{len(x) - n_w}패'
        n_전일잔고 = float(sri_잔고전체.iloc[-2]) if len(sri_잔고전체) >= 2 else np.nan
        n_당일계좌율 = ((n_잔고 / n_전일잔고 - 1) * 100
                   if (n_전일잔고 == n_전일잔고 and n_전일잔고 > 0 and n_잔고 == n_잔고) else np.nan)
        n_당일손익액 = n_잔고 - n_전일잔고 if n_전일잔고 == n_전일잔고 else np.nan

        B.append(f"""
<div class="rowlbl">누적 — 시작부터 {s_기준일}까지</div>
<div class="grid4">
<div class="card"><div class="k">백테 계좌 (개발표본 포함)</div>
<div class="v">{s_pct(n_계좌율)}</div>
<div class="n">{N_계좌_시작 / 10000:,.0f}만 → {n_잔고:,.0f}원 · {dic_전체['일수']}일 {dic_전체['건수']}건</div></div>
<div class="card"><div class="k">홀드아웃 계좌 ({N_계좌_시작 / 10000:,.0f}만 재출발 가정)</div>
<div class="v">{s_pct(n_홀드계좌율)}</div>
<div class="n">{N_계좌_시작 / 10000:,.0f}만 → {n_잔고홀드:,.0f}원 · {dic_홀드['일수']}일 {dic_홀드['건수']}건</div></div>
<div class="card"><div class="k">홀드아웃 거래손익 합</div><div class="v">{s_pct(dic_홀드['합계'])}</div>
<div class="n">거래당 {dic_홀드['거래당']:+.3f}% · 계좌 영향은 분할수만큼 희석</div></div>
<div class="card"><div class="k">1차 판정선까지</div><div class="v">{n_남은1}건</div>
<div class="n">최근 {n_속도:.1f}건/일 → 약 {n_남은일1}거래일 · {s_예상일(n_남은일1)}</div></div>
</div>

<div class="rowlbl">당일 — {s_기준일}</div>
<div class="grid4">
<div class="card"><div class="k">당일 계좌</div>
<div class="v">{s_pct(n_당일계좌율)}</div>
<div class="n">{f"{n_당일손익액:+,.0f}원 · 잔고 {n_잔고:,.0f}원" if n_당일손익액 == n_당일손익액 else "전일 잔고 없음"}</div></div>
<div class="card"><div class="k">당일 거래손익 합</div>
<div class="v">{s_pct(dic_오늘['합계']) if dic_오늘['건수'] else '<span class="mu">거래 없음</span>'}</div>
<div class="n">{f"거래당 {dic_오늘['거래당']:+.3f}%" if dic_오늘['건수'] else '신호 없음 — 나쁜 날 회피도 성과다'}</div></div>
<div class="card"><div class="k">당일 구간별 손익</div>
<div class="v" style="font-size:19px">{s_pct(n_오늘1) if n_오늘건1 else '<span class="mu">-</span>'}
 / {s_pct(n_오늘2) if n_오늘건2 else '<span class="mu">-</span>'}</div>
<div class="n">구간1 / 구간2</div></div>
<div class="card"><div class="k">당일 거래</div>
<div class="v">{dic_오늘['건수']}건</div>
<div class="n">{f"승 {n_승} · 패 {dic_오늘['건수'] - n_승} (승률 {dic_오늘['승률']:.0f}%)<br>" if dic_오늘['건수'] else ''
                }{s_구간요약('구간1')} · {s_구간요약('구간2')}</div></div>
</div>
""")

        # ── 진척
        B.append('<h2>목표 대비 어디까지 왔나</h2>')
        B.append('<div class="grid4">')
        n_남은홀드일 = max(0, N_목표_홀드일 - dic_홀드['일수'])
        n_남은롤링일 = max(0, N_목표_롤링일 - dic_전체['일수'])
        B.append(s_도넛('홀드아웃 일수', dic_홀드['일수'], N_목표_홀드일, '일',
                       f'구간1 1차 판정선<br>{s_예상일(n_남은홀드일)}'))
        B.append(s_도넛('1차 판정선', dic_홀드['건수'], N_목표_건수1, '건',
                       f'거래당 +0.90% 가정<br>약 {n_남은일1}거래일 · {s_예상일(n_남은일1)}'))
        B.append(s_도넛('2차 판정선', dic_홀드['건수'], N_목표_건수2, '건',
                       f'거래당 +0.64% 가정<br>약 {n_남은일2}거래일 · {s_예상일(n_남은일2)}'))
        B.append(s_도넛('롤링 재검증', dic_전체['일수'], N_목표_롤링일, '거래일',
                       f'{N_목표_롤링창}일창 + {N_목표_롤링폴드}폴드 · '
                       f'현재 폴드 {max(0, dic_전체["일수"] - N_목표_롤링창)}개<br>'
                       f'{s_예상일(n_남은롤링일)}'))
        B.append('</div>')
        B.append(f"""
<p class="note">판정선 근거 — 관측 분포(거래당 평균 +0.64%, 표준편차 3.13%, 왜도 1.46)를 부트스트랩해
양측 95%·검정력 80%로 "거래당 기대값이 0보다 크다"를 말하는 데 필요한 거래 수를 구한 값이다.
참 기대값을 개발표본 수준(+0.90%)으로 가정하면 {N_목표_건수1}건, 전체 평균(+0.64%)이면 {N_목표_건수2}건이다.
<b>거래 빈도는 국면에 따라 3배 넘게 변하므로 날짜가 아니라 건수로 판단한다.</b><br>
예상 도달일은 평일만 세어 환산한 값이라 공휴일만큼 뒤로 밀린다. 거래 빈도가 바뀌면 매일 다시 계산된다.</p>
""")

        # ── 성능
        B.append('<h2>성능</h2>')
        B.append('<div class="tw"><table><thead><tr><th class="l">구분</th><th>일수</th><th>거래</th>'
                 '<th>합계</th><th>거래당</th><th>승률</th><th>최대</th><th>최소</th><th>손실일</th>'
                 '</tr></thead><tbody>')
        for s_이름, dic_x in [('개발표본 (~' + S_개발표본_종료 + ')', dic_개발),
                            ('홀드아웃 (' + S_개발표본_종료 + ' 이후)', dic_홀드),
                            ('전체', dic_전체)]:
            B.append(f'<tr><td class="l">{s_이름}</td><td>{dic_x["일수"]}</td><td>{dic_x["건수"]}</td>'
                     f'<td>{s_pct(dic_x["합계"])}</td><td>{s_pct(dic_x["거래당"], 3)}</td>'
                     f'<td>{dic_x["승률"]:.0f}%</td><td>{s_pct(dic_x["최대"])}</td>'
                     f'<td>{s_pct(dic_x["최소"])}</td>'
                     f'<td>{dic_x["손실일"]}/{dic_x["일수"]}</td></tr>')
        B.append('</tbody></table></div>')
        B.append(f"""
<p class="note"><b>"합계"는 거래 수익률을 단순히 더한 값이고 계좌 수익률과 다르다.</b>
진입 한 건에 총자본의 1/분할수만 넣으므로 거래손익은 그만큼 희석되고, 대신 잔고에 복리로 쌓인다.
홀드아웃이 거래손익 합 {dic_홀드['합계']:+.2f}%인데 계좌로는 {n_홀드계좌율:+.2f}%인 이유다.
계좌 환산은 사이징이 총자본 비례라 자본 규모와 무관하므로,
홀드아웃 시작 시점에 {N_계좌_시작 / 10000:,.0f}만원으로 다시 출발했다고 보면
지금 <b>{n_잔고홀드:,.0f}원</b>이다.</p>
""")

        B.append('<h3>구간별 (홀드아웃 기준)</h3>')
        B.append('<div class="tw"><table><thead><tr><th class="l">구간</th><th>거래</th><th>합계</th>'
                 '<th>거래당</th><th>승률</th></tr></thead><tbody>')
        for s_구간 in ['구간1', '구간2']:
            x = self.dic_집계(d_홀드[d_홀드['구간'] == s_구간])
            B.append(f'<tr><td class="l">{s_구간}</td><td>{x["건수"]}</td><td>{s_pct(x["합계"])}</td>'
                     f'<td>{s_pct(x["거래당"], 3)}</td>'
                     f'<td>{f"{x['승률']:.0f}%" if x["건수"] else "-"}</td></tr>')
        B.append('</tbody></table></div>')

        B.append('<h3>최근 10거래일</h3>')
        B.append('<div class="tw"><table><thead><tr><th>일자</th><th>거래</th><th>손익</th>'
                 '<th>구간1</th><th>구간2</th><th>계좌잔고</th></tr></thead><tbody>')
        dic_잔고 = (dict(zip(df_결['일자'].astype(str),
                          pd.to_numeric(df_결['거래후예수금'], errors='coerce')))
                  if len(df_결) else dict())
        for s_d in sorted(df['일자'].unique())[-10:]:
            x = df[df['일자'] == s_d]
            n1 = x[x['구간'] == '구간1']['수익률'].sum()
            n2 = x[x['구간'] == '구간2']['수익률'].sum()
            n_bal = dic_잔고.get(str(s_d), np.nan)
            B.append(f'<tr><td>{s_d}</td><td>{len(x)}</td><td>{s_pct(x["수익률"].sum())}</td>'
                     f'<td>{s_pct(n1)}</td><td>{s_pct(n2)}</td>'
                     f'<td>{f"{n_bal:,.0f}원" if n_bal == n_bal else "-"}</td></tr>')
        B.append('</tbody></table></div>')

        # ── 안정성
        n_t = self.n_t값(d_홀드)
        n_loo홀드 = self.n_loo(d_홀드)
        n_mdd = self.n_낙폭(df_결)
        n_fat = self.n_팻테일(df)
        B.append('<h2>안정성</h2>')
        B.append('<div class="tw"><table><thead><tr><th class="l">지표</th><th>값</th>'
                 '<th class="l">읽는 법</th></tr></thead><tbody>')
        li_행 = [
            ('손실일 비율 (홀드아웃)',
             f'{dic_홀드["손실일"]}/{dic_홀드["일수"]}일'
             + (f' ({dic_홀드["손실일"] / dic_홀드["일수"] * 100:.0f}%)' if dic_홀드['일수'] else ''),
             '일별 결산 손실 없이 유지가 대전제 — 이 비율이 절반을 넘으면 경고'),
            ('최대 낙폭 (백테 계좌)', s_pct(n_mdd),
             '고점 대비 최대 하락. 실계좌가 견딜 수 있는 폭인지로 본다'),
            ('하루빼기 최악 (홀드아웃)', s_pct(n_loo홀드),
             '가장 좋은 하루를 빼도 남는 합계. 한 날에 기대고 있으면 크게 떨어진다'),
            ('팻테일 의존도 (전체)',
             f'{n_fat:.0f}%' if n_fat == n_fat else '-',
             '상위 3건이 총이익에서 차지하는 비중. 높을수록 소수 대박 의존'),
            ('통계 유의성 t값 (홀드아웃)',
             f'{n_t:+.2f}' if n_t == n_t else '-',
             '|t| ≥ 2 라야 "0이 아니다"라고 말할 수 있다. 지금은 표본 부족'),
        ]
        if len(df_실):
            d_실홀드 = df_실[df_실['일자'] > S_개발표본_종료]
            if len(d_실홀드):
                n_실합 = float(d_실홀드['순손익'].sum())
                n_실률 = n_실합 / float(d_실홀드['매수금'].sum()) * 100
                li_행.append(('실매매 실현 (홀드아웃)',
                             f'{n_실합:+,.0f}원 ({n_실률:+.2f}%)',
                             '원장 기준 비용 후 실현손익. 백테와 부호가 갈리면 원인 조사'))
        for s_k, s_v, s_설명 in li_행:
            B.append(f'<tr><td class="l">{s_k}</td><td>{s_v}</td><td class="l">'
                     f'<span class="mu">{s_설명}</span></td></tr>')
        B.append('</tbody></table></div>')

        # ── 파라미터 고정 vs 매일 재최적화 (실패해도 대시보드 자체는 나가야 한다)
        B += self.li_롤링비교()

        # ── 앞으로
        B.append('<h2>앞으로</h2>')
        B.append(f"""
<ul>
<li><b>1차 판정선 {N_목표_건수1}건까지 {n_남은1}건.</b> 최근 속도 {n_속도:.1f}건/일 기준
약 {n_남은일1}거래일 — {s_예상일(n_남은일1)}. 이때 로직의 기대값이 개발표본 수준(+0.90%)이라면
비로소 "0보다 크다"를 80% 확률로 잡아낼 수 있다.</li>
<li><b>기대값이 그보다 낮으면(+0.64%) {N_목표_건수2}건이 필요하다</b> — {n_남은2}건, 약 {n_남은일2}거래일
({s_예상일(n_남은일2)}). 즉 <b>로직이 좋을수록 빨리 증명되고, 애매하면 오래 걸린다.</b></li>
<li><b>롤링 walk-forward 재검증은 총 {N_목표_롤링일}거래일</b>({N_목표_롤링창}일 창 + {N_목표_롤링폴드}폴드)에서
1차로 가능하다. 현재 {dic_전체['일수']}거래일 = 폴드 {max(0, dic_전체['일수'] - N_목표_롤링창)}개.
다만 그때 잡히는 건 큰 효과(+1%p/일)뿐이고, 작은 효과(+0.5%p/일)는 107폴드가 필요해 훨씬 뒤다.</li>
<li><b>지금 할 일은 소액 유지와 표본 축적</b>이다. 판정선 전에 파라미터를 바꾸면
누적 기록의 의미가 사라져 시계가 처음으로 되돌아간다.</li>
</ul>
""")

        s_html = f"""<title>진척 대시보드 — {s_기준일}</title>
<style>{CSS}</style>
<div class="wrap">
<h1>진척 대시보드 — {s_기준일}</h1>
<div class="sub">틱기반매수세 전략 · 개발표본 ~{S_개발표본_종료} / 홀드아웃 그 이후 ·
백테 {dic_전체['일수']}거래일 {dic_전체['건수']}건 · 매일 백테스팅 직후 자동 생성</div>
{''.join(B)}
<div class="ft">bbTrader_claude · analyzer/대시보드.py 자동 생성 ·
모든 수치는 30_거래내역·40_결과정리·주문체결 원장 실측</div>
</div>"""

        os.makedirs(self.folder_리포트, exist_ok=True)
        s_파일명 = f'{s_기준일}_대시보드.html'
        path = os.path.join(self.folder_리포트, s_파일명)
        with open(path, mode='wt', encoding='utf-8') as f:
            f.write(s_html)
        self.make_로그(f'대시보드 생성 - {s_파일명} ({len(s_html.encode("utf-8")):,} bytes)')

        # 텔레그램 본문 - 자세한 건 리포트에 있으니 여기서는 세 줄과 이정표 하나만
        s_날짜 = f'{s_기준일[:4]}-{s_기준일[4:6]}-{s_기준일[6:]}'
        # 수익률 세 줄은 모두 '계좌' 기준으로 맞춘다 (거래손익 합과 섞으면 헷갈린다)
        s_오늘값 = f'{n_당일계좌율:+.2f}%' if n_당일계좌율 == n_당일계좌율 else '-'
        s_이정표 = s_예상일(n_남은일1)
        s_이정표 = ('도달' if s_이정표 == '도달'
                 else f'{int(s_이정표[5:7])}/{int(s_이정표[8:10])} 무렵')
        # 구분은 빈 줄로만 한다 - 괘선 문자(─ 등)는 폰트에 따라 폭이 1칸/2칸으로 갈려 줄맞춤이 깨진다
        # 값은 전부 ASCII로 만들고 단위(원·건·일 등)는 라벨로 옮긴다 (윗쪽 s_행 주석 참조)
        li_줄 = [
            s_행('오늘 계좌', s_오늘값 if dic_오늘['건수'] else '-'),
            s_행('홀드아웃 계좌', f'{n_홀드계좌율:+.2f}%'),
            s_행('전체 계좌', f'{n_계좌율:+.2f}%'),
            s_행('잔고', f'{n_잔고:,.0f}'),
            '',
            s_행('오늘 거래', f'{dic_오늘["건수"]}'),
            s_행('오늘 승패', f'{n_승} / {dic_오늘["건수"] - n_승}' if dic_오늘['건수'] else '-'),
            s_행('홀드아웃 일수', f'{dic_홀드["일수"]}'),
            s_행('홀드아웃 건수', f'{dic_홀드["건수"]}'),
            '',
            s_행('판정선까지', f'{n_남은1}'),
            s_행('예상 도달', s_이정표.replace(' 무렵', '')),
        ]
        # 박스는 <blockquote> - <pre> 는 텔레그램이 코드블록으로 보고 복사(</>) 버튼을 얹는다.
        # 안쪽 <code> 는 고정폭 유지용 (줄맞춤이 ASCII 고정폭에 의존한다)
        s_요일 = '월화수목금토일'[pd.Timestamp(s_기준일).weekday()]
        s_메세지 = (f'<b>═══  진척 대시보드  ═══</b>\n\n'
                 f'{s_날짜} ({s_요일})\n'
                 f'<blockquote><code>{chr(10).join(li_줄)}</code></blockquote>')
        return (s_파일명, s_메세지), None

    # =================================================================
    def send_텔레그램(self, s_파일명, s_메세지):
        """ 텔레그램 발송 - 파일 첨부·버튼 없이 링크만 (설정 없으면 조용히 건너뜀) """
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from xapi.API_telegram import TelegramAPI
            tg = TelegramAPI()
            s_url = f'{self.s_웹주소}/{urllib.parse.quote(s_파일명)}'
            b_결과 = tg.send_메세지(s_메세지=s_메세지, li_링크=[(s_파일명, s_url)], b_HTML=True)
            self.make_로그(f'텔레그램 발송 {"성공" if b_결과 else "건너뜀/실패"}')
            return b_결과
        except Exception as e:
            self.make_로그(f'텔레그램 발송 예외 - {type(e).__name__}: {e}')
            return False


# noinspection NonAsciiCharacters,PyPep8Naming
def run(b_발송=True):
    """ 실행 함수 - 실패해도 예외를 밖으로 던지지 않는다 (런처의 다른 작업을 막지 않기 위함) """
    try:
        d = Dashboard()
    except Exception as e:
        print(f'대시보드 초기화 실패 - {type(e).__name__}: {e}')
        return
    try:
        t_결과, s_오류 = d.make_리포트()
        if s_오류:
            d.make_로그(f'대시보드 생성 건너뜀 - {s_오류}')
            return
        if b_발송:
            d.send_텔레그램(*t_결과)
    except Exception as e:
        d.make_로그(f'대시보드 실패 - {type(e).__name__}: {e}')
        try:
            from xapi.API_telegram import TelegramAPI
            TelegramAPI().send_메세지(s_메세지=f'[진척 대시보드] 생성 실패\n'
                                            f'{type(e).__name__}: {e}')
        except Exception:
            pass


if __name__ == '__main__':
    run(b_발송='--no-send' not in sys.argv)
