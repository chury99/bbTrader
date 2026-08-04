# -*- coding: utf-8 -*-
""" 구간1(개장 09:00~09:10) 흐름추종 로직 — 일일 홀드아웃 검증 도구 (독립 실행, 실매매 미연동)

    목적: 파라미터를 '고정'해 두고, 새 거래일이 생길 때마다 그 날을 미지의 날로 평가해
          정직한 표본 외 성적을 누적한다. 배포 여부는 이 누적 기록으로 판단한다.

    로직 (2026-07-27 확정, 이후 변경 금지 — 변경하면 누적 기록의 의미가 사라짐):
      진입(09:00~09:10 한정)
        - 유효 매수 체결(|거래량|>2, 즉 1·2주 제외)이 10초 창 기준 초당 R회 이상 (절대 기준)
        - AND 단가 상승 (10초 전 대비)
        - AND 순매수비율(체결률과 동일한 10초 창) >= 순매수하한
      청산
        - 트레일링 스탑: 보유중 고점 대비 트레일% 하락 (※ 매수세 소멸 청산보다 우수함이 검증됨)
        - 안전장치: 손절 %, 최대보유, 장마감
    ※ 09:10 이후(구간2)는 기존 bot_백테스팅_틱기반매수세 로직 영역 — 여기서 다루지 않음.

    개발표본(20260716~20260724)과 홀드아웃(20260727~)을 구분해 집계한다.

    사용:
        python analyzer/구간1검증.py            # 새 일자만 평가 → 누적 기록 갱신 + 리포트
        python analyzer/구간1검증.py --rebuild   # 전체 재평가
"""
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ut

# ===== 고정 파라미터 (변경 금지) =====
_구간1_시작, _구간1_종료 = 9 * 3600, 9 * 3600 + 600      # 09:00 ~ 09:10
_체결률하한 = 7.0             # 초당 매수 체결 횟수 하한 (10초 창, 절대)
_순매수하한 = 0.5      # 60초 순매수비율 하한
_산출창 = 10             # 체결률 산출 창 (초)
_상승판정창 = 10          # 단가 상승 판정 (N초 전 대비)
_트레일 = 2.0         # 트레일링 스탑 % (보유중 고점 대비)
_손절 = 1.5           # 손절 %
_최대보유 = 1800       # 최대 보유 (초)
_쿨다운 = 180         # 청산 후 재진입 대기 (초)
_일최대 = 1           # 종목당 1일 최대 진입 - 2→1 (2026-07-28, 재진입 전수검증 결과 배포와 동기화)
_비용 = 0.35          # 왕복 거래비용 % (수수료+세금)
_매수슬립 = 0.20       # 진입 체결 슬리피지 % (백테스팅 _T_매수슬립과 동일 - 실전 대조 기반)
_매도슬립 = 0.08       # 청산 체결 슬리피지 % (백테스팅 _T_매도슬립과 동일) - 0.15→0.08 (2026-08-04 실측 재보정)
_단주 = 2            # |틱거래량| <= 값이면 제외 (1·2주)
_개발표본_종료 = '20260724'   # 이 날짜까지가 로직 개발에 쓰인 표본(=in-sample)
_틱시작일 = '20260716'
_장마감초 = 15 * 3600 + 15 * 60
# 종목선정 (전일 일봉) - bot_백테스팅_틱기반매수세와 동일 기준
_최소거래대금, _최소가격 = 5000.0, 1000.0


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection
class 구간1Validator:
    """ 구간1 로직 일일 홀드아웃 검증 """

    def __init__(self):
        dic = ut.폴더manager.FolderManager().dic_폴더정보
        self.folder_틱 = dic['매수매도|주식체결']
        self.folder_감시 = dic['매수매도|감시종목']
        self.folder_백테 = os.path.join(dic['분석|백테스팅'], '클로드_틱기반매수세')
        self.folder_선정 = os.path.join(self.folder_백테, '10_종목선정')
        self.folder_out = os.path.join(self.folder_백테, '_구간1검증')
        os.makedirs(self.folder_out, exist_ok=True)
        self.path_기록 = os.path.join(self.folder_out, 'df_구간1거래.pkl')
        self.folder_서버 = ('/Volumes/extSSD4tb/80_Backup/10_python_backup/ProjectWork/spTraderV2'
                          if sys.platform == 'darwin' else '')

    # -----------------------------------------------------------------
    def li_일자(self):
        li = sorted(re.findall(r'\d{8}', f)[0] for f in os.listdir(self.folder_틱)
                    if '주식체결_' in f and '.csv' in f)
        s_지금 = pd.Timestamp.now()
        li = [d for d in li if d >= _틱시작일]
        if s_지금.strftime('%H%M') < '1535':      # 당일 장중은 제외 (틱 미완결)
            li = [d for d in li if d != s_지금.strftime('%Y%m%d')]
        return li

    def _load_틱(self, s_일자):
        path = os.path.join(self.folder_틱, f'주식체결_{s_일자}.csv')
        if not os.path.exists(path):
            return None
        df = pd.read_csv(path, encoding='cp949', usecols=['종목코드', '체결시간', '현재가', '거래량'],
                         dtype=str, on_bad_lines='skip')
        df['현재가'] = pd.to_numeric(df['현재가'].str.replace('+', '', regex=False)
                                 .str.replace('-', '', regex=False), errors='coerce')
        df['거래량'] = pd.to_numeric(df['거래량'], errors='coerce')
        df = df.dropna(subset=['현재가', '거래량'])
        df['종목코드'] = df['종목코드'].str.strip()
        s = df['체결시간'].str
        df['초'] = (pd.to_numeric(s[:2], errors='coerce') * 3600 + pd.to_numeric(s[2:4], errors='coerce') * 60
                   + pd.to_numeric(s[4:6], errors='coerce'))
        df = df.dropna(subset=['초'])
        df['초'] = df['초'].astype(int)
        return df[(df['초'] >= 9 * 3600) & (df['초'] <= _장마감초)]

    def _대상종목(self, s_일자):
        """ 종목선정 pkl 우선, 없으면 감시종목 + 전일 일봉으로 동일 기준 산출 """
        path = os.path.join(self.folder_선정, f'df_종목선정_{s_일자}.pkl')
        if os.path.exists(path):
            df = pd.read_pickle(path)
            df = df.loc[df['종목선정']]
            return dict(zip(df['종목코드'], df['종목명']))
        # 폴백: 감시종목 + 일봉 캐시
        path_감시 = os.path.join(self.folder_감시, f'dic_감시종목_{s_일자}.pkl')
        if not os.path.exists(path_감시):
            return {}
        dic_감시 = pd.read_pickle(path_감시)
        # 두 키(조회순위포함/조회순위미포함)는 감시 100종목의 분할일 뿐 - 합친 뒤 거래대금·가격으로 걸러야 매매 대상이 된다
        li = dic_감시.get('조회순위포함', []) + dic_감시.get('조회순위미포함', [])
        folder_일봉 = os.path.join(self.folder_서버, '데이터', '차트캐시', '일봉1')
        if not os.path.exists(folder_일봉):
            return {}
        fs = sorted(f for f in os.listdir(folder_일봉)
                    if '.pkl' in f and re.findall(r'\d{8}', f)[0] < s_일자)
        if not fs:
            return {}
        dic_일봉 = pd.read_pickle(os.path.join(folder_일봉, fs[-1]))
        out = {}
        for code in li:
            d = dic_일봉.get(code)
            if d is None or len(d) == 0:
                continue
            r = d.iloc[-1]
            if r['거래대금(백만)'] >= _최소거래대금 and r['종가'] >= _최소가격:
                out[code] = r['종목명']
        return out

    # -----------------------------------------------------------------
    @staticmethod
    def _시계열(g):
        """ 종목 하나의 초당 시계열 (가격 / 매수체결건 / 매수·매도량) """
        if len(g) < 500:
            return None
        유효 = g.loc[g['거래량'].abs() > _단주]
        매수틱 = 유효.loc[유효['거래량'] > 0]
        매도틱 = 유효.loc[유효['거래량'] < 0]
        가격 = g.groupby('초')['현재가'].last()
        s = np.arange(가격.index.min(), 가격.index.max() + 1)
        p = 가격.reindex(s).ffill()
        return dict(s=s.astype(np.int32), price=p.values.astype(float),
                    매수건=매수틱.groupby('초').size().reindex(s).fillna(0).values.astype(float),
                    매수량=매수틱.groupby('초')['거래량'].sum().reindex(s).fillna(0).values.astype(float),
                    매도량=(-매도틱.groupby('초')['거래량'].sum()).reindex(s).fillna(0).values.astype(float))

    @staticmethod
    def _거래(a, s_일자, s_종목코드, s_종목명):
        """ 진입/청산 시뮬 (고정 파라미터) """
        s, p = a['s'], a['price']
        n = len(s)
        매수율 = pd.Series(a['매수건']).rolling(_산출창).sum().values / _산출창
        순비율 = ((pd.Series(a['매수량'] - a['매도량']).rolling(_산출창).sum())
                 / pd.Series(a['매수량'] + a['매도량']).rolling(_산출창).sum().replace(0, np.nan)).values
        상승 = np.full(n, False)
        if n > _상승판정창:
            상승[_상승판정창:] = p[_상승판정창:] > p[:-_상승판정창]
        ent = ((매수율 >= _체결률하한) & 상승 & (np.nan_to_num(순비율, nan=-9) >= _순매수하한)
               & (s >= _구간1_시작) & (s < _구간1_종료))
        ent = np.nan_to_num(ent, nan=False).astype(bool)
        idx = np.where(ent)[0]

        li, i = [], 0
        while len(li) < _일최대:
            pos = np.searchsorted(idx, i)
            if pos >= len(idx):
                break
            e = int(idx[pos])
            n_매수가 = p[e] * (1 + _매수슬립 / 100)      # 진입 체결 슬리피지
            n_손절가 = n_매수가 * (1 - _손절 / 100)
            n_피크 = n_매수가
            i_청산, s_사유, n_스탑가 = None, None, n_손절가
            i_끝 = min(n - 1, e + _최대보유)
            for t in range(e + 1, i_끝 + 1):
                if s[t] >= _장마감초:
                    i_청산, s_사유 = t, '장마감'; break
                n_피크 = max(n_피크, p[t])
                # 스탑 = max(고정손절, 고점대비 트레일선) - 둘 중 위쪽이 먼저 터치되므로 max가 실제 체결에 부합
                # (백테스팅 bot_백테스팅_틱기반매수세 와 동일 관례)
                n_스탑가 = max(n_손절가, n_피크 * (1 - _트레일 / 100))
                if p[t] <= n_스탑가:
                    i_청산 = t
                    s_사유 = '손절' if n_스탑가 == n_손절가 else '트레일'
                    break
            if i_청산 is None:
                i_청산, s_사유 = i_끝, '보유초과'
            # 청산가: 스탑을 터치한 그 초의 실제 가격은 이미 스탑 아래 → 둘 중 낮은 쪽 (백테스팅과 동일 관례)
            n_매도가 = (min(n_스탑가, p[i_청산]) if s_사유 in ('손절', '트레일') else p[i_청산])
            n_매도가 *= (1 - _매도슬립 / 100)          # 청산 체결 슬리피지
            li.append(dict(일자=s_일자, 종목코드=s_종목코드, 종목명=s_종목명,
                           매수시각=int(s[e]), 매도시각=int(s[i_청산]),
                           매수가=float(n_매수가), 매도가=float(n_매도가),
                           수익률=(n_매도가 / n_매수가 - 1) * 100 - _비용,
                           사유=s_사유, 보유초=int(s[i_청산] - s[e])))
            i = i_청산 + _쿨다운
        return li

    # -----------------------------------------------------------------
    def eval_일자(self, s_일자):
        df_틱 = self._load_틱(s_일자)
        dic_종목 = self._대상종목(s_일자)
        if df_틱 is None or not dic_종목:
            return pd.DataFrame()
        li = []
        for code, g in df_틱[df_틱['종목코드'].isin(dic_종목)].groupby('종목코드', sort=False):
            a = self._시계열(g)
            if a is None:
                continue
            li += self._거래(a, s_일자, code, dic_종목.get(code, code))
        return pd.DataFrame(li)

    def update(self, rebuild=False):
        """ 미평가 일자만 평가해 누적 기록 갱신 """
        기존 = (pd.read_pickle(self.path_기록)
                if os.path.exists(self.path_기록) and not rebuild else pd.DataFrame())
        평가완료 = set(기존['일자'].unique()) if len(기존) else set()
        # 거래 0건인 날도 평가완료로 기록하기 위해 별도 파일 사용
        path_일자 = os.path.join(self.folder_out, 'li_평가일자.pkl')
        li_완료 = set(pd.read_pickle(path_일자)) if os.path.exists(path_일자) and not rebuild else set()
        li_완료 |= 평가완료
        li_대상 = [d for d in self.li_일자() if d not in li_완료]
        if li_대상:
            print(f'신규 평가 대상: {li_대상}')
        li_new = []
        for d in li_대상:
            df = self.eval_일자(d)
            li_new.append(df)
            li_완료.add(d)
            print(f'  {d}: {len(df)}건, {df["수익률"].sum() if len(df) else 0:+.2f}%')
        df_전체 = pd.concat([기존] + [x for x in li_new if len(x)], ignore_index=True) \
            if (len(기존) or any(len(x) for x in li_new)) else pd.DataFrame()
        pd.to_pickle(df_전체, self.path_기록)
        pd.to_pickle(sorted(li_완료), path_일자)
        if len(df_전체):
            df_전체.to_csv(self.path_기록.replace('.pkl', '.csv'), index=False, encoding='cp949')
        return df_전체, sorted(li_완료)

    # -----------------------------------------------------------------
    @staticmethod
    def _요약(df):
        if df is None or len(df) == 0:
            return dict(건수=0, 승률=0.0, 합계=0.0, 평균승=0.0, 평균패=0.0, 기대=0.0)
        r = df['수익률'].values
        w, l = r[r > 0], r[r <= 0]
        return dict(건수=len(r), 승률=len(w) / len(r) * 100, 합계=float(r.sum()),
                    평균승=float(w.mean()) if len(w) else 0.0,
                    평균패=float(l.mean()) if len(l) else 0.0, 기대=float(r.mean()))

    def report(self, rebuild=False):
        df, li_일자 = self.update(rebuild=rebuild)
        L = []
        L.append('=' * 78)
        L.append('구간1(09:00~09:10) 흐름추종 — 일일 홀드아웃 검증')
        L.append(f'고정 파라미터: 체결률>={_체결률하한}/초(창{_산출창}s) · 순매수>={_순매수하한} · 단가상승{_상승판정창}s'
                 f' · 트레일{_트레일}% · 손절{_손절}% · 최대보유{_최대보유}s · 일최대{_일최대}')
        L.append('=' * 78)
        if df is None or len(df) == 0:
            L.append('거래 기록 없음')
            return '\n'.join(L)

        df = df.copy()
        df['구분'] = np.where(df['일자'] <= _개발표본_종료, '개발표본', '홀드아웃')
        일자_개발 = [d for d in li_일자 if d <= _개발표본_종료]
        일자_홀드 = [d for d in li_일자 if d > _개발표본_종료]

        L.append(f'\n[일자별]  (평가일 {len(li_일자)}일: 개발표본 {len(일자_개발)} / 홀드아웃 {len(일자_홀드)})')
        L.append(f'{"일자":>10} | {"구분":>8} | {"거래":>4} | {"승":>3} | {"손익":>8} | {"최대":>7} | {"최소":>7}')
        L.append('-' * 66)
        for d in li_일자:
            g = df[df['일자'] == d]
            구분 = '개발표본' if d <= _개발표본_종료 else '홀드아웃'
            if len(g) == 0:
                L.append(f'{d:>10} | {구분:>8} | {0:>4} | {0:>3} | {0.0:>+7.2f}% | {"-":>7} | {"-":>7}')
            else:
                L.append(f'{d:>10} | {구분:>8} | {len(g):>4} | {int((g["수익률"]>0).sum()):>3} | '
                         f'{g["수익률"].sum():>+7.2f}% | {g["수익률"].max():>+6.2f}% | {g["수익률"].min():>+6.2f}%')

        L.append(f'\n[집계]')
        L.append(f'{"구분":>10} | {"일수":>4} | {"거래":>4} | {"승률":>5} | {"평균승":>7} | {"평균패":>7} | '
                 f'{"거래당":>7} | {"합계":>8} | {"손실일":>4}')
        L.append('-' * 82)
        for 구분, 일자들 in [('개발표본', 일자_개발), ('홀드아웃', 일자_홀드), ('전체', li_일자)]:
            sub = df[df['일자'].isin(일자들)]
            s = self._요약(sub)
            neg = sum(1 for d in 일자들 if sub[sub['일자'] == d]['수익률'].sum() < -1e-9)
            L.append(f'{구분:>10} | {len(일자들):>4} | {s["건수"]:>4} | {s["승률"]:>4.0f}% | '
                     f'{s["평균승"]:>+6.2f}% | {s["평균패"]:>+6.2f}% | {s["기대"]:>+6.3f}% | '
                     f'{s["합계"]:>+7.2f}% | {neg:>4}')

        h = self._요약(df[df['일자'].isin(일자_홀드)])
        L.append(f'\n[판정 가이드]')
        L.append(f'  홀드아웃 누적: {len(일자_홀드)}일 / {h["건수"]}건 / {h["합계"]:+.2f}% / 거래당 {h["기대"]:+.3f}%')
        if len(일자_홀드) < 15:
            L.append(f'  → 아직 판단 이름 (권장 15일 이상). {15-len(일자_홀드)}일 더 필요.')
        elif h['기대'] > 0 and h['합계'] > 0:
            L.append('  → 홀드아웃 누적 양수. 슬리피지 여유 확인 후 배포 검토 가능.')
        else:
            L.append('  → 홀드아웃 누적 음수. 배포 보류.')
        L.append('  ※ 이 로직은 소수의 큰 수익에 의존(추세추종). 중앙값은 0 부근이 정상.')

        L.append(f'\n[청산 사유]  {df["사유"].value_counts().to_dict()}')
        L.append(f'[상위 거래]')
        for _, r in df.nlargest(5, '수익률').iterrows():
            L.append(f'  {r["수익률"]:+6.2f}% | {r["종목명"]}({r["종목코드"]}) {r["일자"]} | '
                     f'보유 {r["보유초"]}초 | {r["사유"]}')
        return '\n'.join(L)

    def run(self, rebuild=False):
        txt = self.report(rebuild=rebuild)
        print(txt)
        path = os.path.join(self.folder_out, f'_리포트_{pd.Timestamp.now():%Y%m%d_%H%M%S}.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(txt)
        print(f'\n리포트 저장: {path}')


def run():
    """ 실행 함수 """
    구간1Validator().run(rebuild='--rebuild' in sys.argv)


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print('\n### [ KeyboardInterrupt detected ] ###')
