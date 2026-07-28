# -*- coding: utf-8 -*-
""" 틱기반매수세 전략 walk-forward 검증 도구 (독립 실행)

    목적: "과거에 예쁜 파라미터"가 아니라 "다음 미지의 날에도 버는 파라미터"를 근거 있게 고른다.
    방식: 진입로직을 (임계값 무관) 초당지표 캐시 + (임계값 적용) 순수 시뮬로 분리 →
          파라미터 스윕이 값싸짐. expanding window로 과거학습→다음날검증(OOS).

    단일 진실원천: 현행 파라미터(_T_*)는 bot_백테스팅_틱기반매수세에서 그대로 임포트.
    충실도 게이트: 현행 파라미터로 재시뮬한 결과가 기존 30_거래내역과 거래단위까지 일치해야만
                   최적화 결과를 출력한다(로직 복제분이 원본과 어긋나면 즉시 실패로 드러남).

    사용:
        python analyzer/워크포워드검증.py            # 캐시 자동 빌드 → 검증 → walk-forward 리포트
        python analyzer/워크포워드검증.py --rebuild   # 지표 캐시 강제 재생성
"""
import os
import re
import sys
import itertools

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 리포지토리 루트
import ut
from analyzer import bot_백테스팅_틱기반매수세 as BT   # 현행 파라미터/기준 재사용


# noinspection NonAsciiCharacters,PyPep8Naming,PyAttributeOutsideInit,SpellCheckingInspection
class WalkForward:
    """ 틱기반매수세 전략 walk-forward 최적화·검증 """

    def __init__(self):
        dic_폴더 = ut.폴더manager.FolderManager().dic_폴더정보
        self.folder_틱 = dic_폴더['매수매도|주식체결']
        self.folder_백테 = os.path.join(dic_폴더['분석|백테스팅'], '클로드_틱기반매수세')
        self.folder_선정 = os.path.join(self.folder_백테, '10_종목선정')
        self.folder_거래 = os.path.join(self.folder_백테, '30_거래내역')
        self.folder_캐시 = os.path.join(self.folder_백테, '_wf캐시')
        os.makedirs(self.folder_캐시, exist_ok=True)

        self.s_틱시작일 = '20260716'                # 틱 유효 시작일 (원본 AnalyzerBot.s_틱시작일과 동일)
        self.n_장마감초 = 15 * 3600 + 15 * 60      # 15:15 강제청산 (= 원본 AnalyzerBot.n_장마감초)
        self.단주 = int(BT._T_단주)                 # 지표 캐시는 단주 필터에 의존 → 스윕 대상 아님
        self.n_구간2시작 = (9 * 3600 + BT._구간1_종료) if BT._구간1_사용 else 0   # 구간1과 시간대 분리
        # ※ 이 도구는 구간2(눌림매매) 파라미터만 스윕한다. 구간1은 analyzer/구간1검증.py 담당

        # 현행 파라미터(단일 진실원천) → dic_파라미터 딕셔너리
        self.dic_현행파라미터 = dict(
            순매수비율=BT._T_순매수비율, 거래강도=BT._T_거래강도, 최소거래량=BT._T_최소거래량,
            이격최소=BT._T_이격최소, 이격최대=BT._T_이격최대, 체결속도=BT._T_체결속도,
            덩어리상한=BT._T_덩어리상한, 일최대거래=BT._T_일최대거래, 쿨다운=BT._T_쿨다운,
            손절=BT._T_손절, 트레일=BT._T_트레일, 본전발동=BT._T_본전발동,
            최대보유=BT._T_최대보유, 비용=BT._T_비용)
        # 스윕에서 고정할 항목(진입 임계값·청산만 스윕)
        self.li_고정키 = ['이격최소', '본전발동', '최대보유', '쿨다운', '일최대거래', '비용']
        self.dic_고정값 = {k: self.dic_현행파라미터[k] for k in self.li_고정키}

    # =================================================================
    # 틱 로딩 (원본 _load_틱 재현)
    # =================================================================
    def _load_틱(self, s_일자):
        path = os.path.join(self.folder_틱, f'주식체결_{s_일자}.csv')
        if not os.path.exists(path):
            return None
        li_col = ['종목코드', '체결시간', '현재가', '거래량', '고가']
        df = pd.read_csv(path, encoding='cp949', usecols=li_col, dtype=str, on_bad_lines='skip')
        for c in ['현재가', '고가']:
            df[c] = pd.to_numeric(df[c].str.replace('+', '', regex=False).str.replace('-', '', regex=False),
                                  errors='coerce')
        df['거래량'] = pd.to_numeric(df['거래량'], errors='coerce')
        df = df.dropna(subset=['현재가', '거래량', '고가'])
        df['종목코드'] = df['종목코드'].str.strip()
        s = df['체결시간'].str
        df['초'] = (pd.to_numeric(s[:2], errors='coerce') * 3600
                   + pd.to_numeric(s[2:4], errors='coerce') * 60
                   + pd.to_numeric(s[4:6], errors='coerce'))
        df = df.dropna(subset=['초'])
        df['초'] = df['초'].astype(int)
        df = df[(df['초'] >= 9 * 3600) & (df['초'] <= 15 * 3600 + 30 * 60)]
        return df

    # =================================================================
    # 초당 지표 계산 (원본 _make_거래_종목 489-522행, 임계값 무관 부분)
    # =================================================================
    def _indic_종목(self, df_종목):
        if len(df_종목) < 500:
            return None
        df_유효 = df_종목.loc[df_종목['거래량'].abs() > self.단주]
        df_매수틱 = df_유효.loc[df_유효['거래량'] > 0]
        df_매수 = df_매수틱.groupby('초')['거래량'].sum()
        df_매도 = -df_유효.loc[df_유효['거래량'] < 0].groupby('초')['거래량'].sum()
        sri_가격 = df_종목.groupby('초')['현재가'].last()
        sri_당일고가 = df_종목.groupby('초')['고가'].last()

        ary_초 = np.arange(sri_가격.index.min(), sri_가격.index.max() + 1)
        d = pd.DataFrame(index=ary_초)
        d['price'] = sri_가격.reindex(ary_초).ffill()
        d['high'] = sri_당일고가.reindex(ary_초).ffill()
        d['매수량'] = df_매수.reindex(ary_초).fillna(0)
        d['매도량'] = df_매도.reindex(ary_초).fillna(0)
        d['틱수'] = df_유효.groupby('초')['거래량'].size().reindex(ary_초).fillna(0)
        d['최대매수틱'] = df_매수틱.groupby('초')['거래량'].max().reindex(ary_초).fillna(0)

        sri_전체 = d['매수량'] + d['매도량']
        sri_순매수60 = (d['매수량'] - d['매도량']).rolling(60).sum()
        sri_전체60 = sri_전체.rolling(60).sum()
        d['전체60'] = sri_전체60
        d['순매수비율'] = sri_순매수60 / sri_전체60.replace(0, np.nan)
        sri_기준거래량 = sri_전체.rolling(300).sum().shift(60) / 5
        d['거래강도'] = sri_전체60 / sri_기준거래량.replace(0, np.nan)
        d['이격률'] = (d['high'].shift(1) - d['price']) / d['high'].shift(1) * 100
        d['변동폭300'] = d['price'].rolling(300).max() - d['price'].rolling(300).min()

        sri_틱수300 = d['틱수'].rolling(300).sum().shift(60)
        d['체결속도'] = d['틱수'].rolling(60).sum() / (sri_틱수300 / 5).replace(0, np.nan)
        sri_평균틱 = sri_전체.rolling(300).sum().shift(60) / sri_틱수300.replace(0, np.nan)
        d['덩어리배수'] = d['최대매수틱'].rolling(60).max() / sri_평균틱.replace(0, np.nan)

        return dict(
            ary_초=ary_초.astype(np.int32),
            price=d['price'].values.astype(np.float64),
            변동폭300=d['변동폭300'].values.astype(np.float64),
            순매수비율=d['순매수비율'].values.astype(np.float64),
            거래강도=d['거래강도'].values.astype(np.float64),
            전체60=d['전체60'].values.astype(np.float64),
            체결속도=d['체결속도'].values.astype(np.float64),
            덩어리배수=d['덩어리배수'].values.astype(np.float64),
            이격률=d['이격률'].values.astype(np.float64))

    # =================================================================
    # 대상일자 / 선정종목 / 캐시
    # =================================================================
    def li_일자(self):
        """ 틱파일 존재 & 틱시작일 이후 일자 (오름차순) """
        li = sorted(re.findall(r'\d{8}', f)[0] for f in os.listdir(self.folder_틱)
                    if '주식체결_' in f and '.csv' in f)
        return [d for d in li if d >= self.s_틱시작일]

    def _선정종목(self, s_일자):
        path = os.path.join(self.folder_선정, f'df_종목선정_{s_일자}.pkl')
        if not os.path.exists(path):
            return None
        df = pd.read_pickle(path).set_index('종목코드', drop=False)
        return df.loc[df['종목선정']]

    def build_cache(self, s_일자, force=False):
        """ 하루치 지표 캐시 (종목코드 -> arrays). 이미 있으면 로딩 """
        path = os.path.join(self.folder_캐시, f'ind_{s_일자}.pkl')
        if os.path.exists(path) and not force:
            return pd.read_pickle(path)
        df_틱 = self._load_틱(s_일자)
        df_sel = self._선정종목(s_일자)
        if df_틱 is None or df_sel is None or df_sel.empty:
            pd.to_pickle({}, path)
            return {}
        li_대상 = df_sel['종목코드'].tolist()
        df_틱대상 = df_틱[df_틱['종목코드'].isin(li_대상)]
        out = dict()
        for code, g in df_틱대상.groupby('종목코드', sort=False):
            arr = self._indic_종목(g)
            if arr is None:
                continue
            arr['종목명'] = df_sel.loc[code, '종목명']
            out[code] = arr
        pd.to_pickle(out, path)
        return out

    def load_caches(self, rebuild=False):
        li_d = self.li_일자()
        return li_d, {d: self.build_cache(d, force=rebuild) for d in li_d}

    # =================================================================
    # 순수 시뮬레이터 (원본 _make_거래_종목 524-600행 재현)
    # =================================================================
    def _sim_종목(self, arr, s_일자, code, dic_파라미터):
        ary_초 = arr['ary_초']
        ary_가격 = arr['price']
        ary_변동폭 = arr['변동폭300']
        n_길이 = len(ary_초)

        n_웜업 = ary_초[0] + 360
        ary_진입 = ((arr['순매수비율'] > dic_파라미터['순매수비율']) & (arr['거래강도'] > dic_파라미터['거래강도'])
                  & (arr['전체60'] >= dic_파라미터['최소거래량'])
                  & (arr['체결속도'] >= dic_파라미터['체결속도']) & (arr['덩어리배수'] <= dic_파라미터['덩어리상한'])
                  & (ary_초 > n_웜업) & (ary_초 < self.n_장마감초)
                  & (ary_초 >= self.n_구간2시작)
                  & (arr['이격률'] >= dic_파라미터['이격최소']) & (arr['이격률'] < dic_파라미터['이격최대']))
        ary_진입 = np.nan_to_num(ary_진입, nan=False).astype(bool)
        idx_후보 = np.where(ary_진입)[0]

        li = []
        i = 0
        while len(li) < dic_파라미터['일최대거래']:
            pos = np.searchsorted(idx_후보, i)
            if pos >= len(idx_후보):
                break
            i_진입 = int(idx_후보[pos])
            n_매수가 = ary_가격[i_진입] * (1 + BT._T_매수슬립 / 100)
            n_손절가 = n_매수가 * (1 - dic_파라미터['손절'] / 100)

            i_시작 = i_진입 + 1
            ary_구간 = ary_가격[i_시작:]
            ary_피크 = np.maximum.accumulate(np.concatenate(([n_매수가], ary_구간)))[1:]
            ary_스탑 = np.maximum(n_손절가, ary_피크 * (1 - dic_파라미터['트레일'] / 100))
            if dic_파라미터['본전발동'] > 0:
                n_본전가 = n_매수가 * (1 + dic_파라미터['비용'] / 100)
                ary_스탑 = np.where(ary_피크 >= n_매수가 * (1 + dic_파라미터['본전발동'] / 100),
                                   np.maximum(ary_스탑, n_본전가), ary_스탑)
            ary_터치 = ary_구간 <= ary_스탑
            i_스탑 = int(np.argmax(ary_터치)) if ary_터치.any() else n_길이
            i_마감 = int(np.searchsorted(ary_초[i_시작:], self.n_장마감초))
            i_마감 = i_마감 if i_마감 < len(ary_구간) else n_길이
            i_보유초과 = dic_파라미터['최대보유'] - 1
            i_청산상대 = min(i_스탑, i_마감, i_보유초과)
            if i_청산상대 >= n_길이 or i_시작 + i_청산상대 >= n_길이:
                i_청산 = n_길이 - 1
                s_사유 = '타임아웃'
            else:
                i_청산 = i_시작 + i_청산상대
                s_사유 = (('손절터치' if ary_스탑[i_스탑] == n_손절가 else '트레일청산') if i_청산상대 == i_스탑 else
                        '보유초과' if i_청산상대 == i_보유초과 else '타임아웃')
            n_매도가 = (min(ary_스탑[i_청산상대], ary_가격[i_청산])
                     if s_사유 in ['손절터치', '트레일청산'] else ary_가격[i_청산])
            n_매도가 *= (1 - BT._T_매도슬립 / 100)

            n_수익률 = (n_매도가 / n_매수가 - 1) * 100 - dic_파라미터['비용']
            li.append(dict(일자=s_일자, 종목코드=code, 매수초=int(ary_초[i_진입]), 매도초=int(ary_초[i_청산]),
                           매수가=n_매수가, 매도가=n_매도가, 수익률=n_수익률, 사유=s_사유))
            i = i_청산 + dic_파라미터['쿨다운']
        return li

    def sim_day(self, cache_day, s_일자, dic_파라미터):
        li = []
        for code, arr in cache_day.items():
            li += self._sim_종목(arr, s_일자, code, dic_파라미터)
        return li

    @staticmethod
    def 성과(li_거래):
        n = len(li_거래)
        if n == 0:
            return dict(매매=0, 승률=0.0, 총손익=0.0, 기대치=0.0)
        r = np.array([t['수익률'] for t in li_거래])
        n_승 = int((r > 0).sum())
        승률 = n_승 / n * 100
        평수 = r[r > 0].mean() if n_승 > 0 else 0.0
        평손 = r[r <= 0].mean() if n - n_승 > 0 else 0.0
        손익비 = 평수 / abs(평손) if 평손 != 0 else 0.0
        기대치 = (승률 / 100 * 손익비) - (1 - 승률 / 100)
        return dict(매매=n, 승률=승률, 총손익=float(r.sum()), 기대치=float(기대치))

    # =================================================================
    # 충실도 게이트: 현행 파라미터 재시뮬 == 기존 30_거래내역
    # =================================================================
    def verify(self, li_일자, caches):
        li_불일치 = []
        for d in li_일자:
            li = self.sim_day(caches[d], d, self.dic_현행파라미터)
            new = sorted((t['종목코드'], round(t['매수가'], 1), round(t['수익률'], 3)) for t in li)
            f = os.path.join(self.folder_거래, f'df_거래내역_{d}.pkl')
            if os.path.exists(f):
                df = pd.read_pickle(f)
                if '구간' in df.columns:
                    df = df[df['구간'] == '구간2']      # 이 도구는 구간2 로직만 복제
                old = sorted((r['종목코드'], round(r['매수가'], 1), round(r['수익률'], 3))
                             for _, r in df.iterrows()) if len(df) else []
            else:
                old = None   # 원본 거래내역 없음(대조 불가) → 건너뜀
            if old is not None and new != old:
                li_불일치.append((d, new, old))
        return li_불일치

    # =================================================================
    # 그리드 & 목적함수
    # =================================================================
    DIC_탐색범위 = dict(
        순매수비율=[0.4, 0.5, 0.6],
        거래강도=[3.0, 4.0, 5.0],
        체결속도=[1.0, 2.5, 3.5],
        덩어리상한=[30.0, 60.0, 9999.0],
        이격최대=[10.0, 14.0, 20.0],
        최소거래량=[5000, 10000],
        손절=[1.5, 2.0],
        트레일=[2.5, 3.0],
    )

    def _손익행렬(self, li_조합, li_키, li_일자, caches):
        """ 조합×일자 -> (총손익, 매매수) """
        li_손익행렬 = []
        for vals in li_조합:
            dic_파라미터 = dict(zip(li_키, vals)); dic_파라미터.update(self.dic_고정값)
            row = {}
            for d in li_일자:
                li = self.sim_day(caches[d], d, dic_파라미터)
                r = np.array([t['수익률'] for t in li]) if li else np.array([])
                row[d] = (float(r.sum()) if len(r) else 0.0, len(r))
            li_손익행렬.append(row)
        return li_손익행렬

    @staticmethod
    def _학습점수(row, days):
        """ 학습셋 점수: (-손실일수, 총손익). 제약: 총매매 >= 학습일수(무거래 퇴행 배제) """
        pnls = [row[d][0] for d in days]
        trades = sum(row[d][1] for d in days)
        if trades < len(days):
            return None
        n_neg = sum(1 for p in pnls if p < -1e-9)
        return (-n_neg, sum(pnls))

    # =================================================================
    # walk-forward 리포트
    # =================================================================
    def report(self, rebuild=False):
        li_d, caches = self.load_caches(rebuild=rebuild)
        li_out = []
        li_out.append(f'대상일자 {len(li_d)}일: {li_d}')

        # --- 충실도 게이트 ---
        li_불 = self.verify(li_d, caches)
        if li_불:
            li_out.append('★ 충실도 검증 실패 — 복제 로직이 원본과 어긋남. 최적화 결과 신뢰 불가:')
            for d, new, old in li_불:
                li_out.append(f'  {d}: 시뮬 {new}  vs  원본 {old}')
            return '\n'.join(li_out)
        li_out.append('충실도 검증 통과 (현행 파라미터 재시뮬 == 기존 30_거래내역, 전 일자 일치)')

        li_키 = list(self.DIC_탐색범위.keys())
        li_조합 = list(itertools.product(*[self.DIC_탐색범위[k] for k in li_키]))
        li_손익행렬 = self._손익행렬(li_조합, li_키, li_d, caches)

        def _최적조합(days):
            n_최적번호, t_최적점수 = None, None
            for i, row in enumerate(li_손익행렬):
                s = self._학습점수(row, days)
                if s is None:
                    continue
                if t_최적점수 is None or s > t_최적점수:
                    t_최적점수, n_최적번호 = s, i
            return n_최적번호, t_최적점수

        cur = {d: self.성과(self.sim_day(caches[d], d, self.dic_현행파라미터))['총손익'] for d in li_d}

        # --- walk-forward (expanding) ---
        li_out.append('')
        li_out.append('=' * 92)
        li_out.append('WALK-FORWARD (expanding)  —  학습: 과거 전체 / 검증: 다음 미지의 1일')
        li_out.append('=' * 92)
        li_out.append(f'{"검증일":>9} | {"학습":>3} | {"표본외 튜닝":>16} | {"표본외 현행":>16} | {"IS학습":>13} | {"오라클(상한)":>13}')
        li_out.append('-' * 92)
        s_oos = s_cur = s_orc = 0.0
        li_폴드선택 = []
        for k in range(2, len(li_d)):
            train, test = li_d[:k], li_d[k]
            n_최적번호, t_최적점수 = _최적조합(train)
            if n_최적번호 is None:
                continue
            dic_튜닝값 = dict(zip(li_키, li_조합[n_최적번호])); dic_튜닝값.update(self.dic_고정값)
            oos_p, oos_n = li_손익행렬[n_최적번호][test]
            cur_p = cur[test]
            oi = max(range(len(li_조합)), key=lambda i: li_손익행렬[i][test][0])
            orc_p, orc_n = li_손익행렬[oi][test]
            s_oos += oos_p; s_cur += cur_p; s_orc += orc_p
            li_폴드선택.append((test, dic_튜닝값))
            li_out.append(f'{test:>9} | {len(train):>3} | {oos_p:>9.2f}% ({oos_n}건) | {cur_p:>9.2f}% '
                          f'| {t_최적점수[1]:>7.1f}%(손{-t_최적점수[0]}) | {orc_p:>8.2f}%({orc_n})')
        li_out.append('-' * 92)
        li_out.append(f'{"합계":>9} | {"":>3} | {s_oos:>9.2f}%        | {s_cur:>9.2f}%        '
                      f'| {"":>13} | {s_orc:>8.2f}%')
        li_out.append(f'→ 튜닝 파라미터가 현행보다 {"우위" if s_oos > s_cur else "열위"} '
                      f'(OOS {s_oos:.2f}% vs {s_cur:.2f}%). 열위면 과거 튜닝이 실전 역효과.')

        # --- 선택 dic_파라미터 안정성 ---
        li_out.append('')
        li_out.append('=== 폴드별 선택 파라미터 (안정적일수록 신뢰, 매 폴드 요동치면 노이즈 과적합) ===')
        for test, t in li_폴드선택:
            li_out.append(f'검증{test}: 순매수{t["순매수비율"]} 강도{t["거래강도"]} 속도{t["체결속도"]} '
                          f'덩어리{t["덩어리상한"]:.0f} 이격max{t["이격최대"]:.0f} 최소량{t["최소거래량"]} '
                          f'손절{t["손절"]} 트레일{t["트레일"]}')

        # --- 국면 진단: 일자별 진입후보(셋업) 수 ---
        li_out.append('')
        li_out.append('=== 국면 진단: 일자별 진입후보(셋업) — 현행 진입필터 통과 초/종목 수 ===')
        dic_파라미터 = self.dic_현행파라미터
        for d in li_d:
            n_초 = n_종목 = 0
            for code, arr in caches[d].items():
                n_웜업 = arr['ary_초'][0] + 360
                m = ((arr['순매수비율'] > dic_파라미터['순매수비율']) & (arr['거래강도'] > dic_파라미터['거래강도'])
                     & (arr['전체60'] >= dic_파라미터['최소거래량'])
                     & (arr['체결속도'] >= dic_파라미터['체결속도']) & (arr['덩어리배수'] <= dic_파라미터['덩어리상한'])
                     & (arr['ary_초'] > n_웜업) & (arr['ary_초'] < self.n_장마감초)
                     & (arr['ary_초'] >= self.n_구간2시작)
                     & (arr['이격률'] >= dic_파라미터['이격최소']) & (arr['이격률'] < dic_파라미터['이격최대']))
                c = int(np.nan_to_num(m, nan=False).astype(bool).sum())
                n_초 += c
                n_종목 += 1 if c > 0 else 0
            li_out.append(f'{d}: 진입후보초 {n_초:>4} | 후보종목 {n_종목:>2}/{len(caches[d])} | '
                          f'총손익 {cur[d]:>6.2f}%')

        return '\n'.join(li_out)

    # =================================================================
    def run(self, rebuild=False):
        txt = self.report(rebuild=rebuild)
        print(txt)
        path = os.path.join(self.folder_백테, f'_wf리포트_{pd.Timestamp.now():%Y%m%d_%H%M%S}.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(txt)
        print(f'\n리포트 저장: {path}')


def run():
    """ 실행 함수 """
    rebuild = '--rebuild' in sys.argv
    WalkForward().run(rebuild=rebuild)


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print('\n### [ KeyboardInterrupt detected ] ###')
