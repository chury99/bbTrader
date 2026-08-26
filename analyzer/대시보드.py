# -*- coding: utf-8 -*-
""" 대시보드 - 네 세트를 나란히 놓고 하루를 마감한다 (매일 백테스팅 직후 자동 실행)

    보여주는 것 - 세 덩어리뿐이다
      1. 요약        - 1번 고정 / 2번 롤링 / 3번 종목별 / 오라클 을
                      틱 보유 전 구간과 최근 20거래일 두 창에서 비교
      2. 일별 실적    - 같은 네 세트의 일자별 손익과 3번-1번 차이
      3. 당일 지표변화 - 그날 잡은 거래마다 1초봉 가격과 지표들이 진입 전후로 어떻게 움직였는지.
                      성적을 재는 자리가 아니라 "무엇을 더 봤어야 했나"를 찾는 자리다.

    네 세트는 전부 같은 격자(648칸)·같은 시뮬·같은 검증일 위에서 나온다.
    청산·구간2·자금관리·비용은 현행과 동일하고 바뀌는 축은 구간1 진입·트레일뿐이다.
    학습창을 못 채운 초기 구간은 '현행 파라미터로 매매한 것'으로 본다 - 그렇게 두지 않으면
    방식마다 분모가 달라져 같은 표에 올릴 수 없다.

    ※ 이 도구는 읽기 전용이다. 백테 산출물을 만들지도 고치지도 않는다.
    ※ 카카오 발송에는 일절 관여하지 않는다 (텔레그램만 사용).

    사용:
        python analyzer/대시보드.py              # 리포트 생성 + 텔레그램 발송
        python analyzer/대시보드.py --no-send     # 생성만 (발송 안 함)
"""
import json
import os
import sys
import unicodedata
import urllib.parse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ut

# ===== 기준 (근거 없이 바꾸지 말 것) =====
N_계좌_시작 = 10_000_000          # 계좌 환산 시작 자본 (각 창의 첫날에 재출발한다고 본다)
N_분할1 = 4.0                    # 구간1 진입당 총자본 ÷ 분할수 (BT._구간1_분할수)
N_분할2 = 3.0                    # 구간2 진입당 총자본 ÷ 분할수 (BT._T_분할수)
N_최근창 = 20                     # 요약 오른쪽 칸에 쓰는 최근 거래일 수
S_리포트폴더 = '클로드분석결과'     # 서버 웹폴더(server_kakao) 하위 폴더명

DIC_이름 = {'고정': '1번 고정', '롤링': '2번 롤링', '종목별': '3번 종목별', '오라클': '오라클'}
DIC_색 = {'고정': '#d29922', '롤링': '#a371f7', '종목별': '#39c5cf', '오라클': '#3fb950'}
# 텔레그램 라벨은 전각만 써야 줄이 맞는다 (아래 s_행 주석 참조) - 숫자도 전각으로 쓴다
DIC_텔레라벨 = {'고정': '１번 고정', '롤링': '２번 롤링', '종목별': '３번 종목', '오라클': '오라클'}
N_텔레_값폭 = 14      # '+277.5+182.6' 까지 들어가는 폭 (전 행이 같아야 줄이 맞는다)

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
h3{font-size:16px;margin:30px 0 8px;color:#e6edf3;}
.sub{color:var(--mu);font-size:14px;margin-bottom:8px;}
p{margin:10px 0;}
.lead{background:var(--panel);border:1px solid var(--bd);border-left:3px solid var(--wn);
border-radius:6px;padding:16px 20px;margin:22px 0;}
.tw{overflow-x:auto;margin:16px 0;-webkit-overflow-scrolling:touch;}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:560px;}
th,td{border:1px solid var(--bd);padding:7px 10px;text-align:right;white-space:nowrap;}
th{background:var(--panel2);color:#e6edf3;font-weight:600;text-align:center;}
td.l,th.l{text-align:left;} td.c{text-align:center;}
tbody tr:nth-child(odd){background:rgba(255,255,255,.017);}
tr.sum td{border-top:2px solid var(--bd);font-weight:600;background:var(--panel2);}
tr.orc td{background:rgba(63,185,80,.06);}
.up{color:var(--up);} .dn{color:var(--dn);} .mu{color:var(--mu);}
.ok{color:var(--ok);font-weight:600;} .wn{color:var(--wn);}
.tag{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:7px;
vertical-align:middle;}
ul{margin:10px 0;padding-left:20px;} li{margin:7px 0;}
.ft{margin-top:60px;padding-top:18px;border-top:1px solid var(--bd);color:var(--mu);font-size:12.5px;}
.note{color:var(--mu);font-size:13px;margin:8px 0;}
code{background:var(--panel2);border:1px solid var(--bd);border-radius:4px;
padding:1px 6px;font-size:12.5px;color:#e6edf3;}
.chart{background:var(--panel);border:1px solid var(--bd);border-radius:6px;
padding:14px 12px 10px;margin:14px 0;}
.chart svg{width:100%;height:auto;display:block;}
.chd{display:flex;flex-wrap:wrap;gap:10px 20px;align-items:baseline;margin-bottom:6px;
padding:0 4px;}
.chd b{font-size:15px;color:#e6edf3;}
.lg{display:grid;grid-template-columns:repeat(2,minmax(0,max-content));
justify-content:start;gap:1px 26px;color:var(--mu);font-size:12px;padding:3px 4px 4px;}
.lg .li{display:flex;align-items:baseline;gap:6px;min-width:0;}
.lg b{color:#c9d1d9;font-weight:600;white-space:nowrap;}
.lg .df{color:#6e7681;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lg .tag{flex:0 0 auto;align-self:center;}
.lg .tag.ln{align-self:center;margin:0;}
@media (max-width:560px){.lg{font-size:11px;gap:1px 14px;}}
.tag.ln{width:15px;height:0;border-top:2px dashed;border-radius:0;background:none !important;
margin-bottom:3px;}
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


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection
class Dashboard:
    """ 대시보드 생성 및 발송 """

    def __init__(self):
        dic_폴더 = ut.폴더manager.FolderManager().dic_폴더정보
        self.folder_백테 = os.path.join(dic_폴더['분석|백테스팅'], '클로드_틱기반매수세')
        self.folder_거래 = os.path.join(self.folder_백테, '30_거래내역')

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
    # 집계
    # =================================================================
    @staticmethod
    def dic_기간(dic_일별, s_방식, li_일자):
        """ 한 방식의 한 구간 집계. 계좌는 구간별 분할수를 반영해 복리로 굴린다 """
        n_손익 = sum(dic_일별[s_방식][d]['손익'] for d in li_일자)
        n_건수 = sum(dic_일별[s_방식][d]['건수'] for d in li_일자)
        n_승 = sum(dic_일별[s_방식][d]['승'] for d in li_일자)
        n_잔고 = float(N_계좌_시작)
        for d in li_일자:
            x = dic_일별[s_방식][d]
            n_잔고 *= (1 + (x['손익1'] / N_분할1 + x['손익2'] / N_분할2) / 100)
        return dict(손익=n_손익, 건수=n_건수, 일수=len(li_일자), 잔고=n_잔고,
                    승률=(n_승 / n_건수 * 100 if n_건수 else np.nan),
                    거래당=(n_손익 / n_건수 if n_건수 else np.nan),
                    손실일=sum(1 for d in li_일자 if dic_일별[s_방식][d]['손익'] < -1e-9),
                    계좌=(n_잔고 / N_계좌_시작 - 1) * 100)

    # =================================================================
    # 구획 1·2 — 요약 / 일별
    # =================================================================
    def li_요약(self, dic_일별, li_일자, li_최근):
        B = ['<h2>요약</h2>']
        B.append('<div class="tw"><table><thead><tr><th class="l">방식</th>'
                 f'<th colspan="4">전체 {li_일자[0]}~{li_일자[-1]} ({len(li_일자)}일)</th>'
                 f'<th colspan="4">최근 {len(li_최근)}일 {li_최근[0]}~{li_최근[-1]}</th></tr>'
                 '<tr><th class="l"></th>'
                 '<th>손익 합</th><th>거래</th><th>승률</th><th>계좌</th>'
                 '<th>손익 합</th><th>거래</th><th>승률</th><th>계좌</th></tr></thead><tbody>')
        for s_방식 in DIC_이름:
            li_x = [self.dic_기간(dic_일별, s_방식, li) for li in (li_일자, li_최근)]
            B.append(f'<tr{" class=\'orc\'" if s_방식 == "오라클" else ""}>'
                     f'<td class="l"><span class="tag" style="background:{DIC_색[s_방식]}">'
                     f'</span>{DIC_이름[s_방식]}</td>'
                     + ''.join(f'<td>{s_pct(x["손익"])}</td><td>{x["건수"]}</td>'
                               f'<td>{x["승률"]:.0f}%</td><td>{s_pct(x["계좌"])}</td>'
                               for x in li_x) + '</tr>')
        B.append('</tbody></table></div>')

        d_고1, d_고2 = (self.dic_기간(dic_일별, '고정', li) for li in (li_일자, li_최근))
        d_종1, d_종2 = (self.dic_기간(dic_일별, '종목별', li) for li in (li_일자, li_최근))
        d_롤1 = self.dic_기간(dic_일별, '롤링', li_일자)
        li_순 = sorted(['고정', '롤링', '종목별'],
                       key=lambda m: -self.dic_기간(dic_일별, m, li_최근)['손익'])
        B.append(f'<p class="note">최근 {len(li_최근)}일 기준 순위는 '
                 f'<b>{" &gt; ".join(DIC_이름[m] for m in li_순)}</b> 순이다. '
                 f'3번 종목별이 1번 고정보다 전체에서 {d_종1["손익"] - d_고1["손익"]:+.2f}%p, '
                 f'최근 {len(li_최근)}일에서 {d_종2["손익"] - d_고2["손익"]:+.2f}%p 앞선다. '
                 f'2번 롤링은 1번보다 {d_롤1["손익"] - d_고1["손익"]:+.2f}%p 뒤진다 — '
                 f'하루 단위로 조합을 갈아끼우는 쪽은 아직 정보가 아니라 잡음을 따라가고 있다.<br>'
                 f'계좌는 각 구간 첫날에 {N_계좌_시작 / 10000:,.0f}만원으로 재출발했다고 본 환산값이다'
                 f'(진입당 총자본÷분할수, 구간1={N_분할1:.0f}·구간2={N_분할2:.0f}). '
                 f'사이징이 총자본 비례라 자본 규모와는 무관하다.</p>')
        return B

    def li_일별(self, dic_일별, li_일자, li_최근):
        B = ['<h2>일별 실적</h2>']
        B.append('<div class="tw"><table><thead><tr><th>일자</th><th>대상</th>'
                 + ''.join(f'<th>{DIC_이름[m]}</th>' for m in DIC_이름)
                 + '<th>3번−1번</th></tr></thead><tbody>')
        for d in li_일자:
            x_종 = dic_일별['종목별'][d]
            s_흐림 = '' if d in li_최근 else ' style="opacity:.55"'
            B.append(f'<tr{s_흐림}><td>{d}</td>'
                     f'<td>{x_종["대상"]}<span class="mu"> · 튜닝 {x_종["튜닝"]}</span></td>'
                     + ''.join(f'<td>{s_pct(dic_일별[m][d]["손익"])}'
                               f'<span class="mu"> ({dic_일별[m][d]["건수"]})</span></td>'
                               for m in DIC_이름)
                     + f'<td>{s_pct(x_종["손익"] - dic_일별["고정"][d]["손익"], s_단위="%p")}</td>'
                       f'</tr>')
        B.append('<tr class="sum"><td>합계</td>'
                 f'<td>{sum(dic_일별["종목별"][d]["대상"] for d in li_일자)}<span class="mu"> · '
                 f'{sum(dic_일별["종목별"][d]["튜닝"] for d in li_일자)}</span></td>'
                 + ''.join(f'<td>{s_pct(self.dic_기간(dic_일별, m, li_일자)["손익"])}'
                           f'<span class="mu"> '
                           f'({self.dic_기간(dic_일별, m, li_일자)["건수"]})</span></td>'
                           for m in DIC_이름)
                 + f'<td>{s_pct(self.dic_기간(dic_일별, "종목별", li_일자)["손익"] - self.dic_기간(dic_일별, "고정", li_일자)["손익"], s_단위="%p")}</td></tr>')
        B.append('</tbody></table></div>')
        B.append(f'<p class="note">괄호 안은 거래 건수. 흐린 줄은 최근 {len(li_최근)}일 구간 밖이다. '
                 f'"대상"은 그날 매매대상으로 선정된 종목 수이고 "튜닝"은 그중 3번이 전용 조합을 '
                 f'얹은 수다 — 나머지는 학습 근거가 없어 현행으로 매매한다.</p>')
        return B


    # =================================================================
    # 구획 3 — 당일 지표 변화
    # =================================================================
    # 계열 설명 - 범례에 이름만 적어 두면 무슨 값인지 되짚어야 한다. 정의를 같이 적는다.
    #   매수량·매도량·건수는 전부 단주(|거래량| <= 2) 제외 기준이다.
    #   범례는 두 줄을 넘지 않아야 하므로 수식만 적고 해석은 붙이지 않는다.
    DIC_계열설명 = {
        'stop': 'max(손절가, 고점x(1-트레일%))',
        '순매수10': '10초 (매수-매도) ÷ (매수+매도)',
        '상승률10': '(현재가 ÷ 10초 전 - 1) x100',
        '체결률10': '10초 매수건수 ÷ 10',
        '매수횟수5': '초당 매수건수의 5초 이동평균',
        '단위비': '매수 1건 크기 ÷ 매도 1건 크기',
        '체결강도롤링': '60초 매수량 ÷ 매도량 x100',
        '체결강도누적': '누계 매수량 ÷ 매도량 x100',
        '체결횟수강도롤링': '60초 매수건수 ÷ 매도건수 x100',
        '순매수비율': '60초 (매수-매도) ÷ (매수+매도)',
        '거래강도': '60초 거래량 ÷ 직전5분 평균',
        '체결속도': '60초 체결건수 ÷ 직전5분 평균',
        '덩어리배수': '60초 최대 매수틱 ÷ 평균 틱크기',
        '이격률': '(직전 당일고가 - 현재가) ÷ 고가 x100',
        '전체60': '60초 매수량 + 매도량 (주)',
    }
    # 패널 정의: (제목, 높이, 좌축 계열, 우축 계열, 기준선, 강건스케일, 기준선 범례)
    #   1·2·3번은 같은 격자를 쓰고 고르는 조합만 다르다 - 그래서 여기 실린 축이 곧
    #   세 방식 전부의 진입 축이다. 구간1은 조합마다 켜고 끄는 축이라 격자 후보값을 긋고,
    #   구간2는 격자에 없어 네 방식이 같은 값을 쓰므로 현행 조건값을 긋는다.
    #   강건스케일 - 상하위 1%를 빼고 눈금을 잡는다. 장 시작 몇 초는 누적 분모가 거의 0이라
    #   체결강도가 수천까지 튀는데, 그 한 점 때문에 나머지 전 구간이 납작해진다.
    #   대신 눈금 밖으로 나간 선은 패널 경계에서 잘라 그린다(clip).
    LI_패널 = [
        ('가격', 172, [('봉', '', 1.0, '봉'), ('stop', '#d29922', 1.4, '스탑')],
         None, [], False, None),

        ('구간1 진입 — 모든 조합이 함께 거는 조건', 118,
         [('순매수10', '#a371f7', 1.6, '순매수비율(10초)')],
         [('상승률10', '#39c5cf', 1.4, '10초 상승률')],
         [('순매수10', None), ('상승률10', None)], True,
         ('현행 조건', '순매수 {순매수10} 이상 · 상승률 0 초과')),

        ('구간1 진입 — 격자 축 (체결 빈도·크기)', 118,
         [('체결률10', '#39c5cf', 1.6, '체결률(10초)'),
          ('매수횟수5', '#a371f7', 1.4, '매수횟수(5초평균)')],
         [('단위비', '#d29922', 1.6, '단위매수÷매도')],
         [('체결률10', None), ('매수횟수5', None), ('단위비', None)], True,
         ('격자 후보', '{체결률10} / {매수횟수5} / {단위비} (전부 하한)')),

        ('구간1 진입 — 격자 축 (체결 강도)', 118,
         [('체결강도롤링', '#d29922', 1.6, '체결강도(60초)'),
          ('체결강도누적', '#8b949e', 1.3, '체결강도(누적)'),
          ('체결횟수강도롤링', '#39c5cf', 1.4, '체결횟수강도(60초)')], None,
         [('체결강도롤링', None), ('체결횟수강도롤링', None)], True,
         ('격자 후보', '{체결강도롤링} — 100이면 매수량 = 매도량')),

        ('구간2 진입 — 매수세 (격자에 없어 네 방식이 같다)', 118,
         [('순매수비율', '#a371f7', 1.6, '순매수비율(60초)')],
         [('거래강도', '#d29922', 1.6, '거래강도')],
         [('순매수비율', None), ('거래강도', None)], True,
         ('현행 조건', '순매수 {순매수비율} 초과 · 강도 {거래강도} 초과')),

        ('구간2 진입 — 체결의 질', 118,
         [('체결속도', '#39c5cf', 1.6, '체결속도')],
         [('덩어리배수', '#d29922', 1.6, '덩어리배수')],
         [('체결속도', None), ('덩어리배수', None)], True,
         ('현행 조건', '속도 {체결속도} 이상 · 덩어리 {덩어리배수} 이하')),

        ('구간2 진입 — 위치·물량', 118,
         [('이격률', '#a371f7', 1.6, '고가대비 이격률')],
         [('전체60', '#d29922', 1.6, '60초 거래량')],
         [('이격률', None), ('전체60', None)], True,
         ('현행 조건', '이격 {이격률}% · 거래량 {전체60}주 이상')),
    ]
    # 그림·표에 싣는 지표 (구간1 축 → 구간2 축 순서)
    LI_지표 = ['순매수10', '상승률10', '체결률10', '매수횟수5', '단위비',
             '체결강도롤링', '체결강도누적', '체결횟수강도롤링',
             '순매수비율', '거래강도', '체결속도', '덩어리배수', '이격률', '전체60']
    DIC_라벨 = {'순매수10': '순매수비율(10초)', '상승률10': '10초 상승률',
              '체결률10': '체결률(10초)', '매수횟수5': '매수횟수(5초평균)',
              '단위비': '단위매수÷매도', '체결강도롤링': '체결강도(60초)',
              '체결횟수강도롤링': '체결횟수강도(60초)', '순매수비율': '순매수비율(60초)',
              '거래강도': '거래강도', '체결속도': '체결속도', '덩어리배수': '덩어리배수',
              '이격률': '고가대비 이격률', '전체60': '60초 거래량'}
    LI_표지표 = [k for k in LI_지표 if k != '체결강도누적']
    N_폭, N_여백L, N_여백R = 1080, 58, 58

    def li_계열(self, wf, s_일자):
        """ 그날 거래별로 1초봉 가격·지표 시계열과 진입시점 스냅샷을 뽑는다 """
        from analyzer import bot_백테스팅_틱기반매수세 as BT
        path = os.path.join(self.folder_거래, f'df_거래내역_{s_일자}.pkl')
        if not os.path.exists(path):
            return list()
        df_거래 = pd.read_pickle(path)
        if not len(df_거래):
            return list()

        df_틱 = wf._load_틱(s_일자)
        if df_틱 is None:
            return list()
        li_코드 = set(df_거래['종목코드'])
        dic_arr, dic_ohlc = dict(), dict()
        for s_코드, g in df_틱.groupby('종목코드', sort=False):
            if s_코드 not in li_코드:
                continue
            arr = wf._indic_종목(g)
            if arr is None:
                continue
            dic_arr[s_코드] = arr
            dic_ohlc[s_코드] = self._dic_ohlc(g, arr['ary_초'])

        def n_초(s_hms):
            h, m, s = str(s_hms).split(':')
            return int(h) * 3600 + int(m) * 60 + int(s)

        li_out = list()
        for _, r in df_거래.iterrows():
            arr = dic_arr.get(r['종목코드'])
            if arr is None:
                continue
            n_창 = BT._구간1_창
            d = pd.DataFrame(dict(초=arr['ary_초'], price=arr['price']))
            for s_k, a_v in dic_ohlc[r['종목코드']].items():
                d[s_k] = a_v
            d['체결률10'] = pd.Series(arr['매수틱수']).rolling(n_창).sum().values / n_창
            sri_매, sri_도 = pd.Series(arr['매수량']), pd.Series(arr['매도량'])
            d['순매수10'] = ((sri_매 - sri_도).rolling(n_창).sum()
                          / (sri_매 + sri_도).rolling(n_창).sum().replace(0, np.nan)).values
            # 구간1 필수 조건인 '상승'은 참·거짓이라 그대로는 못 그린다 - 판정에 쓰는 것과
            # 같은 비교(N초 전 대비)를 %로 펴서 0선 위·아래로 읽게 한다
            sri_가 = pd.Series(arr['price'])
            d['상승률10'] = (sri_가 / sri_가.shift(int(BT._구간1_상승창)) - 1).values * 100
            for s_k in ['체결강도롤링', '체결강도누적', '체결횟수강도롤링', '매수횟수5',
                        '순매수비율', '거래강도', '체결속도', '덩어리배수', '이격률', '전체60']:
                d[s_k] = arr[s_k]
            a_도 = np.nan_to_num(arr['단위매도량'], nan=0.0)
            d['단위비'] = np.divide(np.nan_to_num(arr['단위매수량'], nan=0.0), a_도,
                                 out=np.zeros_like(a_도), where=a_도 > 0)

            n_진입, n_청산 = n_초(r['매수시점']), n_초(r['매도시점'])
            dd = d[(d['초'] >= 9 * 3600) & (d['초'] <= n_청산 + 150)].reset_index(drop=True)
            if len(dd) < 10:
                continue

            # 스탑 궤적 - 진입 이후만 (max(손절가, 고점×(1-트레일)))
            n_매수가 = float(r['매수가'])
            b_g1 = r['구간'] == '구간1'
            n_손절가 = n_매수가 * (1 - (BT._구간1_손절 if b_g1 else BT._T_손절) / 100)
            n_트레일 = BT._구간1_트레일 if b_g1 else BT._T_트레일
            a_stop = np.full(len(dd), np.nan)
            b_후 = (dd['초'] > n_진입).values
            if b_후.any():
                a_피크 = np.maximum.accumulate(
                    np.concatenate(([n_매수가], dd['price'].values[b_후])))[1:]
                a_stop[b_후] = np.maximum(n_손절가, a_피크 * (1 - n_트레일 / 100))

            n_보폭 = max(1, len(dd) // 620)          # 점이 너무 많으면 파일만 커진다
            idx = np.arange(0, len(dd), n_보폭)
            dic_계열 = dict(초=dd['초'].values[idx].astype(int),
                          price=dd['price'].values[idx], stop=a_stop[idx])
            for s_k in self.LI_지표:
                dic_계열[s_k] = dd[s_k].values[idx]
            dic_계열['봉'] = self._dic_봉(dd)

            i0 = int(np.searchsorted(d['초'].values, n_진입))
            li_out.append(dict(코드=r['종목코드'], 종목명=r['종목명'], 구간=r['구간'],
                               진입=n_진입, 청산=n_청산, 매수시점=str(r['매수시점']),
                               매도시점=str(r['매도시점']), 수익률=float(r['수익률']),
                               mfe=float(r['mfe_수익률']), mae=float(r['mae_수익률']),
                               계열=dic_계열,
                               스냅={s_k: float(d[s_k].values[i0]) for s_k in self.LI_지표}))
        return li_out

    # ── 봉 차트 ──────────────────────────────────────────────────
    S_양봉, S_음봉 = '#ff7b72', '#58a6ff'      # 상승 빨강·하락 파랑 (국내 관례)
    LI_봉초 = [1, 2, 3, 5, 10, 15, 30, 60, 120, 300, 600]
    N_봉수 = 170        # 이 개수를 넘지 않는 가장 촘촘한 봉을 고른다
                      #   964px 안에 170봉이면 봉 간격이 5.7px - 몸통과 심지가 갈라져 보이는
                      #   최소선이다. 1초봉을 그대로 그리면 창이 길 때 1px 아래로 눌려
                      #   꺾은선과 다를 게 없어진다.

    @staticmethod
    def _dic_ohlc(df_종목, a_초):
        """ 원 틱에서 초마다 시가·고가·저가를 뽑는다 (종가는 지표 캐시의 price 와 같은 값이다).
            체결이 없는 초는 직전 종가로 채운다 - 네 값이 같은, 몸통 없는 봉이 된다. """
        g = df_종목.groupby('초')['현재가']
        d = pd.DataFrame(dict(o=g.first(), h=g.max(), l=g.min(), c=g.last())).reindex(a_초)
        d['c'] = d['c'].ffill()
        for s_k in ['o', 'h', 'l']:
            d[s_k] = d[s_k].fillna(d['c'])
        return {s_k: d[s_k].values.astype(float) for s_k in ['o', 'h', 'l']}

    @classmethod
    def _dic_봉(cls, dd):
        """ 초 단위 시·고·저·종을 N초씩 묶어 봉으로 만든다.
            묶는 폭만 화면에 맞춰 고르고 값은 그대로 집계한다
            (시가=첫 초의 시가, 고가·저가=구간 최대·최소, 종가=마지막 초의 종가). """
        n_len = len(dd)
        n_폭 = next((n for n in cls.LI_봉초 if n_len / n <= cls.N_봉수), cls.LI_봉초[-1])
        g = dd.groupby(np.arange(n_len) // n_폭)
        return dict(초=g['초'].first().values.astype(int), 폭=n_폭,
                    o=g['o'].first().values, h=g['h'].max().values,
                    l=g['l'].min().values, c=g['price'].last().values)

    def _s_봉(self, dic_봉, t_범위, n_상단, n_높이, a_x):
        """ 봉 하나 = 심지(고가~저가) + 몸통(시가~종가). 몸통이 눌리면 1px 선으로 남긴다 """
        n_lo, n_hi = t_범위
        n_x0, n_x1 = self.N_여백L, self.N_폭 - self.N_여백R
        n_t0 = float(a_x[0])
        n_span = max(1.0, float(a_x[-1]) - n_t0)
        n_피치 = (n_x1 - n_x0) * dic_봉['폭'] / n_span
        n_몸통 = max(1.0, min(9.0, n_피치 * 0.68))
        li = list()
        for n_t, n_o, n_h, n_l, n_c in zip(dic_봉['초'], dic_봉['o'], dic_봉['h'],
                                           dic_봉['l'], dic_봉['c']):
            if not np.isfinite(n_o + n_h + n_l + n_c):
                continue
            n_cx = n_x0 + (n_x1 - n_x0) * (n_t + dic_봉['폭'] / 2 - n_t0) / n_span
            n_y고 = n_상단 + n_높이 * (1 - (n_h - n_lo) / (n_hi - n_lo))
            n_y저 = n_상단 + n_높이 * (1 - (n_l - n_lo) / (n_hi - n_lo))
            n_ya, n_yb = sorted(n_상단 + n_높이 * (1 - (n_v - n_lo) / (n_hi - n_lo))
                                for n_v in (n_o, n_c))
            s_색 = self.S_양봉 if n_c >= n_o else self.S_음봉
            li.append(f'<line x1="{n_cx:.1f}" y1="{n_y고:.1f}" x2="{n_cx:.1f}" '
                      f'y2="{n_y저:.1f}" stroke="{s_색}" stroke-width="1"/>'
                      f'<rect x="{n_cx - n_몸통 / 2:.1f}" y="{n_ya:.1f}" '
                      f'width="{n_몸통:.1f}" height="{max(1.0, n_yb - n_ya):.1f}" '
                      f'fill="{s_색}"/>')
        return ''.join(li)

    @staticmethod
    def _t_범위(a, li_문턱=(), b_강건=False):
        a = np.asarray(a, dtype=float)
        a = a[np.isfinite(a)]
        if not len(a):
            return 0.0, 1.0
        if b_강건 and len(a) > 50:
            n_lo, n_hi = (float(x) for x in np.percentile(a, [1, 99]))
        else:
            n_lo, n_hi = float(a.min()), float(a.max())
        for n_v in li_문턱:
            n_lo, n_hi = min(n_lo, n_v * 0.9), max(n_hi, n_v * 1.1)
        if n_hi - n_lo < 1e-9:
            n_hi = n_lo + 1.0
        n_p = (n_hi - n_lo) * 0.1
        return n_lo - n_p, n_hi + n_p

    def _s_선(self, a_x, a_y, t_범위, n_상단, n_높이, s_색, n_굵기, s_대시=''):
        """ 결측 구간에서 선을 끊어 그린다 (지표는 웜업 전이 비어 있다) """
        n_lo, n_hi = t_범위
        n_x0, n_x1 = self.N_여백L, self.N_폭 - self.N_여백R
        li = list()
        for n_x, n_y in zip(a_x, a_y):
            if not np.isfinite(n_y):
                if li and li[-1] != '|':
                    li.append('|')
                continue
            n_px = n_x0 + (n_x1 - n_x0) * (n_x - a_x[0]) / max(1, a_x[-1] - a_x[0])
            n_py = n_상단 + n_높이 * (1 - (n_y - n_lo) / (n_hi - n_lo))
            li.append(f'{n_px:.1f},{n_py:.1f}')
        return ''.join(f'<polyline points="{seg.strip()}" fill="none" stroke="{s_색}" '
                       f'stroke-width="{n_굵기}" stroke-linejoin="round"{s_대시}/>'
                       for seg in ' '.join(li).split('|') if seg.count(',') >= 2)

    N_상단여백 = 15        # 패널 제목이 들어갈 자리 (칸 사이가 벌어지지 않게 최소로)
    N_눈금웜업 = 60         # 눈금을 잡을 때 무시할 앞부분 (초)
                        #   체결강도누적은 09:00 직후 분모(매도 누계)가 거의 0이라 수천까지 튄다.
                        #   그 1분을 눈금 계산에서 빼면 나머지 전 구간이 제대로 펴진다
                        #   (선 자체는 clip 으로 잘라 그리므로 정보가 사라지지는 않는다).

    @staticmethod
    def _s_범례(li_항목):
        """ 패널 바로 밑에 그 패널의 계열만, 이름과 정의를 같이 나열한다.
            SVG 밖 HTML 로 두는 이유는 화면이 좁아져도 글자가 작아지지 않고 줄바꿈되기 때문이다. """
        li = list()
        for s_색, s_라벨, b_점선, s_설명 in li_항목:
            s_표 = (f'<span class="tag ln" style="border-color:{s_색}"></span>' if b_점선
                   else f'<span class="tag" style="background:{s_색}"></span>')
            s_뒤 = f' <span class="df">{s_설명}</span>' if s_설명 else ''
            li.append(f'<span class="li">{s_표}<b>{s_라벨}</b>{s_뒤}</span>')
        return '<div class="lg">' + ''.join(li) + '</div>'

    def s_차트(self, dic_x, dic_문턱, dic_표기):
        """ 한 거래의 4단 그래프 (가격 / 진입성분 / 강도계열 / 체결 크기·빈도)

            패널마다 SVG 를 따로 그리고 그 아래에 범례를 붙인다 - 넷을 모아 맨 밑에 두면
            어느 선이 어느 칸의 것인지 되짚어야 해서 읽기가 어렵다.
            폭(viewBox)이 전부 같으므로 패널을 나눠도 시간축은 그대로 맞는다. """
        c = dic_x['계열']
        a_x = np.asarray(c['초'], dtype=float)
        n_x0, n_x1 = self.N_여백L, self.N_폭 - self.N_여백R
        n_상단 = self.N_상단여백
        li_블록 = list()

        b_웜업 = a_x >= a_x[0] + self.N_눈금웜업      # 눈금 계산에서 앞 1분을 뺀다
        if not b_웜업.any():
            b_웜업 = np.ones(len(a_x), dtype=bool)

        def n_px(n_t):
            return n_x0 + (n_x1 - n_x0) * (n_t - a_x[0]) / max(1, a_x[-1] - a_x[0])

        for n_p, (s_제목, n_h, li_좌, li_우, li_문턱, b_강건, t_기준범례) \
                in enumerate(self.LI_패널):
            # 한 축에 기준선이 여럿일 수 있다 (격자 후보 5·7·9, 이격 상·하한 등)
            li_문턱 = [(k, n) for k, v in li_문턱
                     for n in (dic_문턱.get(k, ()) if v is None else v)]
            s_clip = f'clip_{dic_x["코드"]}_{dic_x["진입"]}_{n_p}'
            li_svg = [f'<defs><clipPath id="{s_clip}"><rect x="{n_x0}" y="{n_상단}" '
                      f'width="{n_x1 - n_x0}" height="{n_h}"/></clipPath></defs>'
                      f'<text x="{n_x0}" y="{n_상단 - 6}" fill="#8b949e" font-size="11.5">'
                      f'{s_제목}</text>'
                      f'<rect x="{n_x0}" y="{n_상단}" width="{n_x1 - n_x0}" height="{n_h}" '
                      f'fill="#0d1117" stroke="#21262d"/>']
            li_svg += [f'<line x1="{n_x0 + (n_x1 - n_x0) * n_i / 6:.1f}" y1="{n_상단}" '
                       f'x2="{n_x0 + (n_x1 - n_x0) * n_i / 6:.1f}" y2="{n_상단 + n_h}" '
                       f'stroke="#21262d" stroke-width="1"/>' for n_i in range(1, 6)]
            li_범례, b_문턱있음 = list(), False
            for b_우, li_계, s_앵커, n_라벨x in [(False, li_좌, 'end', n_x0 - 6),
                                            (True, li_우 or [], 'start', n_x1 + 6)]:
                if not li_계:
                    continue
                li_해당문턱 = [v for k, v in li_문턱 if any(k == kk for kk, *_ in li_계)]
                a_눈금 = np.concatenate(
                    [(np.concatenate([c['봉']['h'], c['봉']['l']]) if k == '봉'
                      else np.asarray(c[k], dtype=float)[b_웜업 if b_강건 else slice(None)])
                     for k, *_ in li_계])
                t_범위 = self._t_범위(a_눈금, li_해당문턱, b_강건)
                n_스팬 = t_범위[1] - t_범위[0]
                s_형식 = ',.0f' if n_스팬 >= 50 else (',.1f' if n_스팬 >= 5 else ',.2f')
                for n_v in ([t_범위[0], t_범위[1]] if b_우
                            else [t_범위[0], sum(t_범위) / 2, t_범위[1]]):
                    n_py = n_상단 + n_h * (1 - (n_v - t_범위[0]) / (t_범위[1] - t_범위[0]))
                    li_svg.append(f'<text x="{n_라벨x}" y="{n_py + 3.5:.1f}" '
                                  f'text-anchor="{s_앵커}" fill="#6e7681" font-size="10">'
                                  f'{n_v:{s_형식}}</text>')
                for s_k, s_색, n_w, s_라벨 in li_계:
                    if s_k == '봉':
                        n_봉초 = c['봉']['폭']
                        li_svg.append(f'<g clip-path="url(#{s_clip})">'
                                      + self._s_봉(c['봉'], t_범위, n_상단, n_h, a_x) + '</g>')
                        # 양봉·음봉을 두 항목으로 나누면 범례가 3줄이 된다 - 색 견본을 반씩 쪼갠다
                        li_범례.append((f'linear-gradient(90deg,{self.S_양봉} 50%,'
                                        f'{self.S_음봉} 50%)', f'{n_봉초}초봉', False,
                                        '시·고·저·종 — 양봉 빨강 · 음봉 파랑'))
                        continue
                    b_점선 = s_k == 'stop'
                    li_svg.append(f'<g clip-path="url(#{s_clip})">'
                                  + self._s_선(a_x, np.asarray(c[s_k], dtype=float), t_범위,
                                               n_상단, n_h, s_색, n_w,
                                               ' stroke-dasharray="4 3"' if b_점선 else '')
                                  + '</g>')
                    li_범례.append((s_색, s_라벨 + (' · 우축' if b_우 else ''), b_점선,
                                   self.DIC_계열설명.get(s_k, '')))
                for n_v in li_해당문턱:
                    if t_범위[0] <= n_v <= t_범위[1]:
                        n_py = n_상단 + n_h * (1 - (n_v - t_범위[0]) / (t_범위[1] - t_범위[0]))
                        li_svg.append(f'<line x1="{n_x0}" y1="{n_py:.1f}" x2="{n_x1}" '
                                      f'y2="{n_py:.1f}" stroke="#3fb950" stroke-width="1" '
                                      f'stroke-dasharray="5 4" opacity="'
                                      f'{".6" if b_우 else "1"}"/>')
                        b_문턱있음 = True
            for n_t, s_색 in [(dic_x['진입'], '#3fb950'), (dic_x['청산'], '#8b949e')]:
                li_svg.append(f'<line x1="{n_px(n_t):.1f}" y1="{n_상단}" '
                              f'x2="{n_px(n_t):.1f}" y2="{n_상단 + n_h}" stroke="{s_색}" '
                              f'stroke-width="1.3" opacity=".85"/>')

            # 아래 여백 - 눈금 글자가 패널 바닥선에 걸쳐 있어 8px 은 있어야 잘리지 않는다
            # 시간축은 칸마다 붙인다 - 아래 칸까지 눈을 내려야 시각을 알 수 있으면 읽기 어렵다
            n_높이 = n_상단 + n_h + 24
            for n_i in range(7):
                n_t = a_x[0] + (a_x[-1] - a_x[0]) * n_i / 6
                n_tx = n_x0 + (n_x1 - n_x0) * n_i / 6
                # 양 끝은 안쪽으로 붙인다 - 가운데 정렬하면 세로눈금 글자와 겹친다
                s_앵 = 'start' if n_i == 0 else ('end' if n_i == 6 else 'middle')
                li_svg.append(
                    f'<text x="{n_tx:.1f}" y="{n_높이 - 6}" '
                    f'text-anchor="{s_앵}" fill="#6e7681" font-size="10">'
                    f'{int(n_t) // 3600:02d}:{int(n_t) % 3600 // 60:02d}:'
                    f'{int(n_t) % 60:02d}</text>')

            if b_문턱있음 and t_기준범례:
                s_기준라벨, s_기준설명 = t_기준범례
                li_범례.append(('#3fb950', s_기준라벨, True,
                              s_기준설명.format(**dic_표기)))
            if n_p == 0:        # 진입·청산 세로선은 전 패널 공통이라 첫 칸에서만 설명한다
                li_범례 += [('#3fb950', '진입', False, '매수 체결'),
                          ('#8b949e', '청산', False, '매도 체결')]
            li_블록.append(f'<svg viewBox="0 0 {self.N_폭} {n_높이}" role="img" '
                          f'aria-label="{dic_x["종목명"]} {s_제목}">{"".join(li_svg)}</svg>'
                          + self._s_범례(li_범례))

        return (f'<div class="chart">'
                f'<div class="chd"><b>{dic_x["종목명"]}</b> '
                f'<span class="mu">{dic_x["코드"]} · {dic_x["구간"]}</span> '
                f'<span class="mu">진입 {dic_x["매수시점"]} → 청산 {dic_x["매도시점"]} '
                f'({dic_x["청산"] - dic_x["진입"]}초)</span> '
                f'<span>{s_pct(dic_x["수익률"])}</span> '
                f'<span class="mu">최대이익 {dic_x["mfe"]:+.2f}% · '
                f'최대손실 {dic_x["mae"]:+.2f}%</span></div>'
                + ''.join(li_블록) + '</div>')

    def li_지표변화(self, wf, s_일자):
        from analyzer import bot_백테스팅_틱기반매수세 as BT
        B = [f'<h2>당일 지표 변화 — {s_일자}</h2>']
        try:
            li_x = self.li_계열(wf, s_일자)
        except Exception as e:                                  # noqa: BLE001
            self.make_로그(f'지표변화 생략 - {type(e).__name__}: {e}')
            return B + ['<p class="mu">지표 계열을 만들지 못했다.</p>']
        if not li_x:
            return B + ['<p class="mu">그날 거래가 없다 — 신호 없는 날은 그릴 것도 없다.</p>']

        # 기준선 - 구간1 격자 축은 후보값 전부를 긋고(0=끔은 뺀다), 나머지는 현행 조건값을 긋는다.
        #   1·2·3번은 같은 격자를 공유하므로 여기 실린 값이 세 방식 전부의 선택지다.
        from analyzer.롤링워크포워드 import DIC_탐색
        def li_후보(s_축):
            return [float(v) for v in DIC_탐색[s_축] if float(v) > 0]
        dic_문턱 = {
            '순매수10': [float(BT._구간1_순매수)], '상승률10': [0.0],
            '체결률10': li_후보('구간1체결률'), '매수횟수5': li_후보('매수횟수5문턱'),
            '단위비': li_후보('단위비'), '체결강도롤링': li_후보('강도문턱'),
            '체결횟수강도롤링': li_후보('횟수강도문턱'),
            '순매수비율': [float(BT._T_순매수비율)], '거래강도': [float(BT._T_거래강도)],
            '체결속도': [float(BT._T_체결속도)], '덩어리배수': [float(BT._T_덩어리상한)],
            '이격률': [float(BT._T_이격최소), float(BT._T_이격최대)],
            '전체60': [float(BT._T_최소거래량)]}
        dic_표기 = {k: '·'.join(f'{v:,g}' for v in li) for k, li in dic_문턱.items()}
        dic_표기['이격률'] = f'{BT._T_이격최소:g}~{BT._T_이격최대:g}'
        B.append('<p class="mu">그날 실제로 잡은 거래마다 <b>가격 봉과 지표들이 진입 전후로 '
                 '어떻게 움직였는지</b>를 펼쳐 놓은 것이다. 성적을 재는 표가 아니라 '
                 '<b>"무엇을 더 봤어야 했나"를 찾는 자리</b>다. 계열 이름 옆에 그 값이 무엇인지 '
                 '적어 두었다.</p>'
                 '<p class="note"><b>1·2·3번이 쓰는 축을 전부 싣는다.</b> 세 방식은 '
                 f'<b>같은 격자 {len(wf.li_조)}칸</b>을 공유하고 그 안에서 고르는 조합만 다르므로, '
                 '축의 목록은 셋이 똑같다. 구간1 축은 조합마다 켜고 끄는 것이라 '
                 '<b>격자 후보값 전부</b>를 기준선으로 그었고(끄는 값 0은 뺐다), 구간2 축은 '
                 '격자에 없어 <b>네 방식이 같은 값</b>을 쓰므로 현행 조건값을 그었다. '
                 '1번 고정은 구간1 축 가운데 체결률 하나만 켜고 나머지는 꺼 둔 조합이다.</p>'
                 '<p class="note">가격 칸은 <b>봉</b>이다 — 초 단위 시·고·저·종을 묶은 것이고, '
                 '몇 초를 한 봉으로 묶을지는 <b>거래마다 창 길이에 맞춰</b> 고른다(범례에 적어 둔다). '
                 '보유가 길수록 봉이 굵어지므로 칸끼리 봉 길이를 곧바로 견주면 안 된다.</p>'
                 '<p class="note">공통 — 지표 계열은 전부 <b>1초 격자</b> 위에서 계산하고, '
                 f'매수량·매도량·체결건수는 전부 <b>단주(|거래량| ≤ {BT._T_단주}) 제외</b> 기준이다'
                 '(가격·고가는 전체 틱을 쓴다). 창 표기는 그 초까지의 뒤돌아보는 길이다 — '
                 '"60초"면 직전 60초 합, "누적"이면 장 시작부터의 누계다. '
                 '가로축은 09:00부터 청산 2분 30초 뒤까지이고, 세로 눈금은 앞 1분을 빼고 '
                 '상하위 1%를 잘라 잡는다(장 초반 누적 지표가 튀어 나머지가 눌리는 것을 막는다).</p>')

        B.append('<h3>진입 순간 스냅샷</h3>')
        B.append('<div class="tw"><table><thead><tr><th class="l">종목</th><th>구간</th>'
                 '<th>진입</th><th>보유</th><th>수익률</th><th>최대이익</th><th>최대손실</th>'
                 + ''.join(f'<th>{self.DIC_라벨[k]}</th>' for k in self.LI_표지표)
                 + '</tr></thead><tbody>')
        for x in sorted(li_x, key=lambda v: -v['수익률']):
            B.append(f'<tr><td class="l">{x["종목명"]}</td>'
                     f'<td class="c"><span class="mu">{x["구간"]}</span></td>'
                     f'<td>{x["매수시점"]}</td>'
                     f'<td>{x["청산"] - x["진입"]}초</td><td>{s_pct(x["수익률"])}</td>'
                     f'<td>{s_pct(x["mfe"])}</td><td>{s_pct(x["mae"])}</td>'
                     + ''.join((f'<td>{x["스냅"][k]:,.0f}</td>'
                                if abs(x['스냅'][k]) >= 1000
                                else f'<td>{x["스냅"][k]:,.2f}</td>'
                                if x['스냅'][k] == x['스냅'][k] else '<td class="mu">-</td>')
                               for k in self.LI_표지표) + '</tr>')
        B.append('</tbody></table></div>')

        li_승 = [x for x in li_x if x['수익률'] > 0]
        li_패 = [x for x in li_x if x['수익률'] <= 0]
        if li_승 and li_패:
            n_승강도 = float(np.mean([x['스냅']['체결강도롤링'] for x in li_승]))
            n_패강도 = float(np.mean([x['스냅']['체결강도롤링'] for x in li_패]))
            n_승비 = float(np.mean([x['스냅']['단위비'] for x in li_승]))
            n_패비 = float(np.mean([x['스냅']['단위비'] for x in li_패]))
            B.append(f'<p class="note">이날 승자 {len(li_승)}건과 패자 {len(li_패)}건의 진입 순간 '
                     f'평균은 체결강도 <b>{n_승강도:,.0f} vs {n_패강도:,.0f}</b>, '
                     f'단위매수÷매도 <b>{n_승비:,.2f} vs {n_패비:,.2f}</b>였다. '
                     f'표본이 한 자릿수이므로 <b>발견이 아니라 눈에 걸린 것</b>일 뿐이다 — '
                     f'하루치로 축을 넣거나 빼지 않는다.</p>')
        B.append('<p class="note">거래마다 <b>구간1 축과 구간2 축을 모두</b> 그린다. '
                 '구간1 거래에 구간2 칸이 붙어 있어도 그 값이 조건을 넘었는지는 그 진입과 '
                 '아무 상관이 없다(반대도 같다) — 두 구간이 같은 순간을 어떻게 다르게 보는지 '
                 '견주라고 남겨 둔 것이다.</p>')

        for x in li_x:
            B.append(self.s_차트(x, dic_문턱, dic_표기))

        B.append('<h3>이 그림에서 꺼내볼 만한 축</h3><ul>'
                 '<li><b>상한 문턱</b> — 지금 격자의 체결강도·체결횟수강도·단위비는 전부 '
                 '<b>하한</b>(이상이면 진입)이다. 같은 지표를 <b>상한</b>으로 걸어 과열 진입을 '
                 '빼는 축은 아직 없다.</li>'
                 '<li><b>문턱을 넘는 속도·지속시간</b> — 지금은 넘었는지만 본다. 얼마나 빨리 '
                 '넘었는지, 몇 초째 넘어 있었는지는 축에 없다.</li>'
                 '<li><b>고가 대비 위치</b> — 구간2에는 이격률 상·하한이 있지만 구간1에는 없다.</li>'
                 '<li><b>손실의 종류</b> — 진입 직후 곧장 역행한 손실과, 한참 올랐다가 트레일에 '
                 '되돌려준 손실은 고칠 곳이 정반대인데 지금은 한 덩어리로 센다.</li>'
                 '<li><b>신호 동시성</b> — 같은 순간에 여러 종목이 함께 신호를 낼 때와 홀로 뜰 때를 '
                 '나누는 축이 없다.</li></ul>'
                 '<p class="note">전부 <b>그날 하루를 보고 떠올린 것</b>이라 그대로 넣으면 안 된다. '
                 '축 하나를 격자에 넣으려면 후보로 <b>사전 등록</b>한 뒤 전 구간에서 훑고 대조군을 '
                 '붙여야 한다.</p>')
        return B

    # =================================================================
    # 리포트
    # =================================================================
    def make_리포트(self):
        from analyzer.종목별롤링워크포워드 import 종목별롤링워크포워드
        wf = 종목별롤링워크포워드()
        li_일자, dic_일별, _ = wf.평가_세방식()
        if not li_일자:
            return None, '손익행렬 비었음'
        li_최근 = li_일자[-N_최근창:]
        s_기준일 = li_일자[-1]

        B = list()
        B.append(f"""<div class="lead">
네 세트를 <b>같은 격자({len(wf.li_조)}칸)·같은 시뮬·같은 검증일</b> 위에서 나란히 돌린 결과다.
청산·구간2·자금관리·비용은 전부 현행과 동일하고 바뀌는 축은 구간1 진입·트레일뿐이다.
학습창을 아직 못 채운 초기 구간은 <b>현행 파라미터로 매매한 것으로 본다</b>
(2번은 앞 10거래일, 3번은 종목의 출현 이력이 없는 종목·일).
</div>""")
        B += self.li_요약(dic_일별, li_일자, li_최근)
        B += self.li_일별(dic_일별, li_일자, li_최근)
        B += self.li_지표변화(wf, s_기준일)

        s_html = f"""<title>대시보드 — {s_기준일}</title>
<style>{CSS}</style>
<div class="wrap">
<h1>대시보드 — {s_기준일}</h1>
<div class="sub">틱기반매수세 전략 · 1번 고정 / 2번 롤링 / 3번 종목별 / 오라클 ·
틱 보유 전 구간 {li_일자[0]}~{li_일자[-1]} {len(li_일자)}거래일 · 격자 {len(wf.li_조)}칸 ·
매일 백테스팅 직후 자동 생성</div>
{''.join(B)}
<div class="ft">bbTrader_claude · analyzer/대시보드.py 자동 생성 · 종목별 손익행렬
(종목 × 일자 × {len(wf.li_조)}조합, 충실도 게이트 통과) 실측</div>
</div>"""

        os.makedirs(self.folder_리포트, exist_ok=True)
        s_파일명 = f'{s_기준일}_대시보드.html'
        with open(os.path.join(self.folder_리포트, s_파일명), mode='wt', encoding='utf-8') as f:
            f.write(s_html)
        self.make_로그(f'대시보드 생성 - {s_파일명} ({len(s_html.encode("utf-8")):,} bytes)')

        # 텔레그램 본문 - 자세한 건 리포트에 있으니 여기서는 네 세트 손익과 당일 성적만
        # 값은 전부 ASCII로 만들고 단위(원·건·일 등)는 라벨로 옮긴다 (윗쪽 s_행 주석 참조)
        d_당일 = {m: dic_일별[m][s_기준일] for m in DIC_이름}
        n_건 = d_당일['고정']['건수']
        n_승 = d_당일['고정']['승']
        li_줄 = list()
        for m in DIC_이름:
            n_전 = self.dic_기간(dic_일별, m, li_일자)['손익']
            n_최 = self.dic_기간(dic_일별, m, li_최근)['손익']
            li_줄.append(s_행(DIC_텔레라벨[m], f'{n_전:+7.1f}{n_최:+7.1f}'))
        li_줄 += ['',
                  s_행('오늘 거래', f'{n_건}'.rjust(N_텔레_값폭)),
                  s_행('오늘 승패',
                       (f'{n_승} / {n_건 - n_승}' if n_건 else '-').rjust(N_텔레_값폭)),
                  s_행('오늘 １번', (f'{d_당일["고정"]["손익"]:+.2f}%'
                                 if n_건 else '-').rjust(N_텔레_값폭)),
                  s_행('오늘 ３번', (f'{d_당일["종목별"]["손익"]:+.2f}%'
                                 if n_건 else '-').rjust(N_텔레_값폭))]
        assert all(b_전각만(s_l.split(chr(32))[0][:N_라벨_전각]) for s_l in li_줄 if s_l)
        s_날짜 = f'{s_기준일[:4]}-{s_기준일[4:6]}-{s_기준일[6:]}'
        s_요일 = '월화수목금토일'[pd.Timestamp(s_기준일).weekday()]
        # 박스는 <blockquote> - <pre> 는 텔레그램이 코드블록으로 보고 복사 버튼을 얹는다
        s_메세지 = (f'<b>═══  대시보드  ═══</b>\n\n'
                 f'{s_날짜} ({s_요일})\n'
                 f'손익 합 — 전체 {len(li_일자)}일 / 최근 {len(li_최근)}일\n'
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
            TelegramAPI().send_메세지(s_메세지=f'[대시보드] 생성 실패\n{type(e).__name__}: {e}')
        except Exception:
            pass


if __name__ == '__main__':
    run(b_발송='--no-send' not in sys.argv)
