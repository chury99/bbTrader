# -*- coding: utf-8 -*-
""" 종목별 롤링워크포워드 — 종목마다 자기 과거로 튜닝한 파라미터를 그 종목에만 적용 (독립 실행)

    가설: 종목마다 고유한 체결 습성이 있고, 전체 평균으로 고른 하나의 파라미터보다
          "그 종목 전용 파라미터"가 다음 날에 더 낫다.

    절차 (매 검증일 d 마다, d 당일 매매대상으로 선정된 종목 각각에 대해)
      1) 직전 40거래일 틱데이터에서 그 종목이 나온 날을 모은다 (선정 여부 무관 - 감시종목이면 틱이 남는다)
      2) 가장 최근 10개 출현일을 학습셋으로 삼아 격자 648칸을 훑는다
      3) 학습구간 거래가 3건 미만인 조합은 후보에서 뺀다 - 표본 1~2건으로 고른 조합은 근거가 아니다
      4) 남은 후보 중 총손익이 가장 큰 조합을 골라 검증일 d 의 그 종목에만 적용한다
         (동률이면 손실일수가 적은 쪽, 그래도 동률이면 현행)
      5) 남은 후보가 하나도 없으면(또는 과거 이력이 아예 없으면) 그 종목은 현행 파라미터로 매매한다

    ※ 5)를 '그날 매매하지 않는다'로 두면 매매 기회를 88% 잘라내고, 잘라낸 몫이 검증창에 따라
      -10.89%p ~ +1.36%p 로 부호가 뒤집혔다. 문턱은 '매매할지'가 아니라 '튜닝을 얹을지'에만
      쓰는 것이 맞다 - 그래서 하이브리드(근거 있으면 전용 파라미터, 없으면 현행)로 확정했다.
    ※ 출현일수 게이트(3일 미만 제외)는 2026-08-20 폐기했다. 그 게이트가 만든 성적 차이는
      전부 '이력이 얕은 종목을 안 건드린' 몫이었고 튜닝 몫은 0이었다. 걸러야 할 것은
      종목의 이력 길이가 아니라 선택의 근거이므로, 문턱을 학습 거래건수로 옮겼다.

    비교 기준 (전부 같은 격자·같은 시뮬·같은 검증일 위에서)
      하이브리드: 위 절차 (근거 있는 종목만 전용 파라미터, 나머지는 현행) - 이 도구의 본체
      현행     : 지금 쓰는 파라미터 고정
      전체롤링 : 기존 analyzer/롤링워크포워드.py — 하루 단위로 조합 하나를 골라 전 종목에 적용
      종목오라클: 종목·일자별 최선 (달성 불가능한 상한)
      무작위   : 종목마다 격자에서 아무거나 골랐을 때의 기대값 - 튜닝이 정보를 쓴 것인지 가리는 대조군

    손익행렬은 (종목 × 일자 × 조합) → (손익, 건수, 승수, 보유초) 로 쌓아 캐시한다.
    종목 단위 시뮬은 서로 독립이므로(자본제약 미모델링) 이 행렬을 종목축으로 더하면
    기존 일단위 행렬과 정확히 같아진다 - 그래서 두 방식을 같은 표 위에서 비교할 수 있다.

    사용:
        python analyzer/종목별롤링워크포워드.py             # 증분 계산 → 리포트
        python analyzer/종목별롤링워크포워드.py --rebuild    # 손익행렬 전량 재계산
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyzer.롤링워크포워드 import 롤링워크포워드, DIC_탐색
from analyzer import bot_백테스팅_틱기반매수세 as BT

N_조회창 = 40          # 종목 출현일을 세는 조회 범위 (거래일)
N_학습창 = 10          # 학습에 쓸 최근 출현일 수 (상한)
N_최소학습건수 = 3      # 학습구간 거래가 이 건수 미만인 조합은 고르지 않는다
                     #   (2026-08-20 변경) 출현일수 게이트를 걷어내고 여기로 옮겼다 -
                     #   막아야 할 것은 '이력이 얕은 종목'이 아니라 '근거 없는 선택'이기 때문.
S_목적 = '총손익'       # 조합 선정 1순위 ('총손익' | '손실일수'), 2순위는 나머지 하나
                     #   (2026-08-20 변경) 일단위 도구에서 물려받은 (-손실일수, 총손익) 사전순은
                     #   종목 단위에서 역효과다 - 학습 표본이 3~4건이라 '손실일수 0'을 만드는
                     #   가장 쉬운 길이 덜 거래하는 조합이라서 목적함수가 그쪽으로 끌린다.
S_행렬파일 = '_종목별손익행렬.pkl'
LI_방식 = ['고정', '롤링', '종목별', '오라클']    # 대시보드가 나란히 놓는 네 세트
N_셀 = 8               # (손익, 건수, 승수, 보유초, 구간1손익, 구간1건수, 구간2손익, 구간2건수)
                     #   구간1은 4분할·구간2는 3분할이라 배분비가 달라, 계좌 수익률로 환산하려면
                     #   구간별로 나눠 놓아야 한다 (2026-08-25 추가).


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection
class 종목별롤링워크포워드(롤링워크포워드):
    """ 종목 단위 walk-forward. 격자·시뮬·비용가정은 롤링워크포워드와 완전히 동일하다 """

    def __init__(self):
        super().__init__()
        self.path_종목행렬 = os.path.join(self.folder_캐시, S_행렬파일)
        self.li_키, self.li_조 = self.li_조합()
        self.n_현행 = next(i for i, v in enumerate(self.li_조)
                        if dict(zip(self.li_키, v))
                        == {k: self.dic_현행파라미터[k] for k in self.li_키})

    # =================================================================
    # 격자 일괄 시뮬 — 한 종목·하루를 전 조합에 대해 한 번에 돌린다
    # =================================================================
    def _cells_종목(self, arr):
        """ (조합수, 4) 배열 반환. 4 = (손익%, 건수, 승수, 보유초합)

            원본 롤링워크포워드._sim_종목 과 같은 결과를 내되,
            조합마다 다시 계산할 필요가 없는 부분(롤링창·구간2 마스크)을 밖으로 빼 재사용한다. """
        ary_초, ary_가격 = arr['ary_초'], arr['price']
        n_길이 = len(ary_초)
        P0 = self.dic_현행파라미터
        n_웜업 = ary_초[0] + 360

        # --- 구간2 진입 (격자에 없는 축이라 고정) ---
        ary_진입2 = ((arr['순매수비율'] > P0['순매수비율']) & (arr['거래강도'] > P0['거래강도'])
                   & (arr['전체60'] >= P0['최소거래량'])
                   & (arr['체결속도'] >= P0['체결속도']) & (arr['덩어리배수'] <= P0['덩어리상한'])
                   & (ary_초 > n_웜업) & (ary_초 < self.n_장마감초)
                   & (ary_초 >= self.n_구간1종료)
                   & (arr['이격률'] >= P0['이격최소']) & (arr['이격률'] < P0['이격최대']))
        idx_후보 = np.where(np.nan_to_num(ary_진입2, nan=False).astype(bool))[0]

        # --- 구간1 성분 (창 길이는 격자에 없으므로 고정) ---
        n_창 = int(P0['구간1창'])
        sri_매수, sri_매도 = pd.Series(arr['매수량']), pd.Series(arr['매도량'])
        a_체결률 = (pd.Series(arr['매수틱수']).rolling(n_창).sum() / n_창).values
        a_순매수 = ((sri_매수 - sri_매도).rolling(n_창).sum()
                 / (sri_매수 + sri_매도).rolling(n_창).sum().replace(0, np.nan)).values
        a_상승 = pd.Series(ary_가격).gt(pd.Series(ary_가격).shift(int(P0['구간1상승창']))).values
        b_공통 = (a_상승 & (a_순매수 >= P0['구간1순매수'])
                & (ary_초 >= self.n_구간1시작) & (ary_초 < self.n_구간1종료))
        b_공통 = np.nan_to_num(b_공통, nan=False).astype(bool)

        # 축별 성분 마스크를 값마다 미리 만들어 둔다 (조합마다 재계산하지 않도록)
        a_강도 = np.nan_to_num(arr['체결강도롤링'], nan=0.0)
        a_횟수강도 = np.nan_to_num(arr['체결횟수강도롤링'], nan=0.0)
        a_도 = np.nan_to_num(arr['단위매도량'], nan=0.0)
        a_단위비 = np.divide(np.nan_to_num(arr['단위매수량'], nan=0.0), a_도,
                          out=np.zeros_like(a_도), where=a_도 > 0)
        a_매수5 = np.nan_to_num(arr['매수횟수5'], nan=0.0)
        b_누적 = a_강도 > np.nan_to_num(arr['체결강도누적'], nan=np.inf)
        dic_성분 = dict(
            구간1체결률={v: a_체결률 >= v for v in DIC_탐색['구간1체결률']},
            강도문턱={v: (a_강도 >= v if v > 0 else None) for v in DIC_탐색['강도문턱']},
            누적비교={v: (b_누적 if v else None) for v in DIC_탐색['누적비교']},
            횟수강도문턱={v: (a_횟수강도 >= v if v > 0 else None) for v in DIC_탐색['횟수강도문턱']},
            단위비={v: (a_단위비 >= v if v > 0 else None) for v in DIC_탐색['단위비']},
            매수횟수5문턱={v: (a_매수5 >= v if v > 0 else None) for v in DIC_탐색['매수횟수5문턱']})

        out = np.zeros((len(self.li_조), N_셀), dtype=np.float64)
        dic_메모 = dict()                      # (구간1 진입지점 서명, 트레일) → 결과
        for i, vals in enumerate(self.li_조):
            P = dict(zip(self.li_키, vals))
            b = b_공통.copy()
            for s_축, v in P.items():
                if s_축 == '구간1트레일':
                    continue
                m = dic_성분[s_축][v]
                if m is not None:
                    b &= m
            idx_g1 = np.where(b)[0]
            t_키 = (idx_g1.tobytes(), P['구간1트레일'])
            if t_키 not in dic_메모:
                dic_메모[t_키] = self._run_거래(ary_초, ary_가격, n_길이, idx_g1, idx_후보,
                                            P['구간1트레일'])
            out[i] = dic_메모[t_키]
        return out

    def _run_거래(self, ary_초, ary_가격, n_길이, idx_g1, idx_후보, n_g1트레일):
        """ 원본 거래 루프 (구간1+구간2 단일 포지션 북) — 집계값만 돌려준다 (N_셀 칸) """
        P0 = self.dic_현행파라미터
        n_손익 = n_건수 = n_승 = n_보유 = 0.0
        n_손익1 = n_건1 = n_손익2 = n_건2 = 0.0
        i, n_횟수1, n_횟수2 = 0, 0, 0
        while True:
            p1 = np.searchsorted(idx_g1, i)
            i1 = (int(idx_g1[p1]) if n_횟수1 < P0['구간1일최대'] and p1 < len(idx_g1) else n_길이)
            p2 = np.searchsorted(idx_후보, i)
            i2 = (int(idx_후보[p2]) if n_횟수2 < P0['일최대거래'] and p2 < len(idx_후보) else n_길이)
            if min(i1, i2) >= n_길이:
                break
            b_g1 = i1 <= i2
            i_진입 = i1 if b_g1 else i2
            n_손절률 = P0['구간1손절'] if b_g1 else P0['손절']
            n_트레일률 = n_g1트레일 if b_g1 else P0['트레일']
            n_최대보유 = P0['구간1최대보유'] if b_g1 else P0['최대보유']
            n_쿨다운 = P0['구간1쿨다운'] if b_g1 else P0['쿨다운']
            n_매수가 = ary_가격[i_진입] * (1 + BT._T_매수슬립 / 100)
            n_손절가 = n_매수가 * (1 - n_손절률 / 100)

            i_시작 = i_진입 + 1
            ary_구간 = ary_가격[i_시작:]
            if len(ary_구간) == 0:
                break
            ary_피크 = np.maximum.accumulate(np.concatenate(([n_매수가], ary_구간)))[1:]
            ary_스탑 = np.maximum(n_손절가, ary_피크 * (1 - n_트레일률 / 100))
            if P0['본전발동'] > 0 and not b_g1:
                n_본전가 = n_매수가 * (1 + P0['비용'] / 100) / (1 - BT._T_매도슬립 / 100)
                ary_스탑 = np.where(ary_피크 >= n_매수가 * (1 + P0['본전발동'] / 100),
                                   np.maximum(ary_스탑, n_본전가), ary_스탑)
            ary_터치 = ary_구간 <= ary_스탑
            i_스탑 = int(np.argmax(ary_터치)) if ary_터치.any() else n_길이
            i_마감 = int(np.searchsorted(ary_초[i_시작:], self.n_장마감초))
            i_마감 = i_마감 if i_마감 < len(ary_구간) else n_길이
            i_보유초과 = n_최대보유 - 1
            i_청산상대 = min(i_스탑, i_마감, i_보유초과)
            if i_청산상대 >= n_길이 or i_시작 + i_청산상대 >= n_길이:
                i_청산, b_스탑청산 = n_길이 - 1, False
            else:
                i_청산 = i_시작 + i_청산상대
                b_스탑청산 = i_청산상대 == i_스탑
            n_매도가 = (min(ary_스탑[i_청산상대], ary_가격[i_청산]) if b_스탑청산 else ary_가격[i_청산])
            n_매도가 *= (1 - BT._T_매도슬립 / 100)

            n_수익률 = (n_매도가 / n_매수가 - 1) * 100 - P0['비용']
            n_손익 += n_수익률
            n_건수 += 1
            n_승 += 1 if n_수익률 > 0 else 0
            n_보유 += int(ary_초[i_청산]) - int(ary_초[i_진입])
            if b_g1:
                n_횟수1 += 1
                n_손익1 += n_수익률
                n_건1 += 1
            else:
                n_횟수2 += 1
                n_손익2 += n_수익률
                n_건2 += 1
            i = i_청산 + n_쿨다운
        return n_손익, n_건수, n_승, n_보유, n_손익1, n_건1, n_손익2, n_건2

    # =================================================================
    # 손익행렬 (종목 × 일자 × 조합) — 새 일자만 증분
    # =================================================================
    def li_틱일자(self):
        """ 헤더만 있는 휴장일 파일은 제외한 실제 거래일 (오름차순)

            당일은 장 마감(15:35) 전이면 틱이 아직 쌓이는 중이라 뺀다 - 반쪽짜리 하루를
            행렬에 굳혀 두면 다음 날 그 종목의 학습셋이 조용히 오염된다.
            마감 뒤에는 넣는다 (대시보드가 백테스팅 직후 호출하므로 당일이 빠지면 늘 하루 늦는다). """
        ts_지금 = pd.Timestamp.now()
        s_오늘 = f'{ts_지금:%Y%m%d}'
        b_마감후 = ts_지금 >= ts_지금.normalize() + pd.Timedelta(hours=15, minutes=40)
        li = list()
        for d in self.li_일자():
            if d > s_오늘 or (d == s_오늘 and not b_마감후):
                continue
            path = os.path.join(self.folder_틱, f'주식체결_{d}.csv')
            if os.path.getsize(path) > 10_000:
                li.append(d)
        return li

    def 행렬갱신(self, rebuild=False, li_일자=None):
        """ {'셀': {일자: {종목: (조합수, N_셀)}}, '선정': {일자: {종목: 종목명}}} 반환 """
        dic = dict(셀=dict(), 선정=dict(), 탐색=DIC_탐색, 셀수=N_셀)
        if os.path.exists(self.path_종목행렬) and not rebuild:
            try:
                dic_저장 = pd.read_pickle(self.path_종목행렬)
                # 탐색축이나 셀 구성이 바뀌면 캐시를 버린다 - 폭이 다른 배열이 섞이면 조용히 깨진다
                if dic_저장.get('탐색') == DIC_탐색 and dic_저장.get('셀수') == N_셀:
                    dic = dic_저장
            except (OSError, EOFError, KeyError, ValueError):
                pass

        li_일자 = li_일자 or self.li_틱일자()

        # 선정 정보 자기치유 - 비어 있는 일자는 매번 다시 읽는다.
        #   틱이 먼저 쌓이고 백테스팅(=종목선정)이 나중에 도는 날이 있어서, 처음 담을 때
        #   비었다고 그대로 굳히면 그 하루가 영영 대상 0종목으로 남는다.
        #   (2026-08-25 실제로 그렇게 굳은 날이 생겨 추가했다)
        for d in [x for x in li_일자 if x in dic['셀'] and not dic['선정'].get(x)]:
            df_sel = self._선정종목(d)
            if df_sel is not None and len(df_sel):
                dic['선정'][d] = dict(zip(df_sel['종목코드'], df_sel['종목명']))
                pd.to_pickle(dic, self.path_종목행렬)

        li_신규 = [d for d in li_일자 if d not in dic['셀']]
        for d in li_신규:
            df_틱 = self._load_틱(d)
            if df_틱 is None:
                continue
            df_sel = self._선정종목(d)
            dic['선정'][d] = (dict(zip(df_sel['종목코드'], df_sel['종목명']))
                            if df_sel is not None and len(df_sel) else dict())
            dic_일 = dict()
            for code, g in df_틱.groupby('종목코드', sort=False):
                arr = self._indic_종목(g)
                if arr is None:
                    continue
                dic_일[code] = self._cells_종목(arr).astype(np.float32)
            dic['셀'][d] = dic_일
            print(f'  {d} 완료 - 종목 {len(dic_일)}개 / 선정 {len(dic["선정"][d])}개', flush=True)
            pd.to_pickle(dic, self.path_종목행렬)
        return dic, li_일자, li_신규

    # =================================================================
    # 충실도 게이트 — 현행 조합의 일합계가 기존 30_거래내역과 맞는가
    # =================================================================
    def verify_행렬(self, dic, li_일자):
        li_불일치 = list()
        for d in li_일자:
            if d not in dic['셀']:
                continue
            path = os.path.join(self.folder_거래, f'df_거래내역_{d}.pkl')
            if not os.path.exists(path):
                continue
            df = pd.read_pickle(path)
            n_원본, n_원본건 = (float(df['수익률'].sum()), len(df)) if len(df) else (0.0, 0)
            li_sel = list(dic['선정'].get(d, dict()))
            n_시뮬 = sum(float(dic['셀'][d][c][self.n_현행, 0])
                       for c in li_sel if c in dic['셀'][d])
            n_시뮬건 = sum(int(dic['셀'][d][c][self.n_현행, 1])
                        for c in li_sel if c in dic['셀'][d])
            if abs(n_시뮬 - n_원본) > 1e-3 or n_시뮬건 != n_원본건:
                li_불일치.append((d, n_시뮬, n_시뮬건, n_원본, n_원본건))
        return li_불일치

    # =================================================================
    # 평가
    # =================================================================
    def _고른조합(self, li_행렬, n_최소건수=N_최소학습건수, s_목적=None):
        """ 학습셋 셀들의 리스트 → 조합번호. 근거 있는 후보가 없으면 None

            1순위 s_목적(기본 총손익 최대), 동률이면 2순위(손실일수 최소),
            그래도 동률이면 현행 조합을 우선한다
            (동률을 임의로 깨면 그 임의성이 성적으로 잡히므로 보수적으로 둔다).
            학습구간 거래가 n_최소건수 미만인 조합은 아예 후보에서 뺀다. """
        s_목적 = s_목적 or S_목적
        a = np.stack(li_행렬)                                   # (학습일수, 조합수, 4)
        a_손익 = a[:, :, 0]
        a_건수 = a[:, :, 1].sum(axis=0)
        a_손실일 = (a_손익 < -1e-9).sum(axis=0).astype(float)
        a_합 = a_손익.sum(axis=0)
        b_유효 = a_건수 >= n_최소건수
        if not b_유효.any():
            return None
        li_축 = ([a_합, -a_손실일] if s_목적 == '총손익' else [-a_손실일, a_합])
        idx = np.where(b_유효)[0]
        for a_축 in li_축:                                       # 사전순 - 앞 축부터 최대값만 남긴다
            idx = idx[a_축[idx] >= a_축[idx].max() - 1e-9]
            if len(idx) == 1:
                break
        return int(self.n_현행) if self.n_현행 in idx else int(idx[0])

    def 평가(self, n_조회창=N_조회창, n_학습창=N_학습창, n_최소건수=N_최소학습건수,
             rebuild=False):
        dic, li_일자, _ = self.행렬갱신(rebuild=rebuild)
        li_일자 = [d for d in li_일자 if d in dic['셀']]
        li_폴드, li_종목행 = list(), list()
        for n_i, d in enumerate(li_일자):
            li_조회 = li_일자[max(0, n_i - n_조회창):n_i]
            dic_sel = dic['선정'].get(d, dict())
            if not li_조회 or not dic_sel:
                continue
            dic_셀 = dict(하이브리드=0.0, 현행=0.0, 오라클=0.0, 무작위=0.0, 튜닝분=0.0, 튜닝분현행=0.0)
            dic_건 = dict(하이브리드=0, 현행=0, 튜닝분=0)
            dic_승 = dict(하이브리드=0, 현행=0)
            n_튜닝 = n_현행회귀 = n_현행선택 = n_대상 = 0
            for code, s_명 in dic_sel.items():
                if code not in dic['셀'][d]:
                    continue
                n_대상 += 1
                cell = dic['셀'][d][code]
                li_출현 = [p for p in li_조회 if code in dic['셀'].get(p, dict())]
                li_학습 = li_출현[-n_학습창:]
                n_조 = (self._고른조합([dic['셀'][p][code] for p in li_학습], n_최소건수)
                       if li_학습 else None)
                b_튜닝 = n_조 is not None
                if not b_튜닝:                        # 근거 없음 → 현행 파라미터로 매매 (하이브리드)
                    n_조, n_현행회귀 = self.n_현행, n_현행회귀 + 1
                else:
                    n_튜닝 += 1
                    n_현행선택 += 1 if n_조 == self.n_현행 else 0
                    dic_셀['튜닝분'] += float(cell[n_조, 0])
                    dic_셀['튜닝분현행'] += float(cell[self.n_현행, 0])
                    dic_건['튜닝분'] += int(cell[n_조, 1])
                dic_셀['하이브리드'] += float(cell[n_조, 0])
                dic_건['하이브리드'] += int(cell[n_조, 1])
                dic_승['하이브리드'] += int(cell[n_조, 2])
                dic_셀['현행'] += float(cell[self.n_현행, 0])
                dic_건['현행'] += int(cell[self.n_현행, 1])
                dic_승['현행'] += int(cell[self.n_현행, 2])
                dic_셀['오라클'] += float(cell[:, 0].max())
                dic_셀['무작위'] += float(cell[:, 0].mean())
                a_학 = (np.stack([dic['셀'][p][code] for p in li_학습]) if li_학습 else None)
                li_종목행.append(dict(일자=d, 종목코드=code, 종목명=s_명, 학습일수=len(li_학습),
                                    출현일수=len(li_출현), 조합=n_조, 튜닝=b_튜닝,
                                    학습건수=(int(a_학[:, n_조, 1].sum()) if a_학 is not None else 0),
                                    손익=float(cell[n_조, 0]), 건수=int(cell[n_조, 1]),
                                    승=int(cell[n_조, 2]),
                                    현행손익=float(cell[self.n_현행, 0]),
                                    현행건수=int(cell[self.n_현행, 1])))
            li_폴드.append(dict(검증일=d, 대상=n_대상, 튜닝=n_튜닝, 현행회귀=n_현행회귀,
                              현행선택=n_현행선택, **{f'{k}손익': v for k, v in dic_셀.items()},
                              하이브리드건수=dic_건['하이브리드'], 현행건수=dic_건['현행'],
                              튜닝분건수=dic_건['튜닝분'],
                              하이브리드승=dic_승['하이브리드'], 현행승=dic_승['현행']))
        return dic, li_일자, li_폴드, pd.DataFrame(li_종목행)

    # =================================================================
    # 세 방식 + 오라클 일자별 집계 (대시보드용)
    # =================================================================
    def 평가_세방식(self, rebuild=False, n_학습창=N_학습창, n_조회창=N_조회창):
        """ 1번 고정 / 2번 롤링 / 3번 종목별 / 오라클 을 같은 행렬 위에서 일자별로 집계

            학습창을 아직 못 채운 초기 구간은 '현행 파라미터로 매매한 것'으로 본다
            (2번은 앞 n_학습창 거래일, 3번은 출현 이력이 없는 종목·일). 그렇게 두지 않으면
            방식마다 분모가 달라져 같은 표에 올릴 수 없다.

            반환: (li_일자, {방식: {일자: 집계}}, {일자: {종목코드: (조합번호, 튜닝여부)}}) """
        dic, li_일자, _ = self.행렬갱신(rebuild=rebuild)
        # 매매대상이 아직 없는 일자(백테스팅 전)는 뺀다 - 대상 0종목인 하루가 표에 끼면
        # 손익 0으로 보이지만 실제로는 '아직 모른다'라서 뜻이 다르다
        li_일자 = [d for d in li_일자 if d in dic['셀'] and dic['선정'].get(d)]

        # --- 일합 행렬 (선정종목만) - 2번 롤링과 일단위 오라클이 쓴다
        dic_일합 = dict()
        for d in li_일자:
            a = np.zeros((len(self.li_조), N_셀))
            for code in dic['선정'].get(d, dict()):
                if code in dic['셀'][d]:
                    a += dic['셀'][d][code]
            dic_일합[d] = a

        # --- 2번 롤링: 직전 n_학습창 거래일로 조합 하나
        dic_롤조합 = dict()
        for n_i, d in enumerate(li_일자):
            if n_i < n_학습창:
                dic_롤조합[d] = (self.n_현행, False)
                continue
            a = np.stack([dic_일합[p] for p in li_일자[n_i - n_학습창:n_i]])
            b_유효 = a[:, :, 1].sum(axis=0) >= n_학습창
            if not b_유효.any():
                dic_롤조합[d] = (self.n_현행, False)
                continue
            a_점수 = np.where(b_유효,
                            -(a[:, :, 0] < -1e-9).sum(axis=0) * 1e6 + a[:, :, 0].sum(axis=0),
                            -np.inf)
            dic_롤조합[d] = (int(np.argmax(a_점수)), True)

        # --- 3번 종목별: 종목마다 자기 출현일로 조합 하나
        dic_종조합 = dict()
        for n_i, d in enumerate(li_일자):
            li_조회 = li_일자[max(0, n_i - n_조회창):n_i]
            dic_종조합[d] = dict()
            for code in dic['선정'].get(d, dict()):
                if code not in dic['셀'][d]:
                    continue
                li_출현 = [p for p in li_조회 if code in dic['셀'].get(p, dict())]
                li_학습 = li_출현[-n_학습창:]
                n_조 = (self._고른조합([dic['셀'][p][code] for p in li_학습]) if li_학습 else None)
                dic_종조합[d][code] = ((self.n_현행, False) if n_조 is None else (n_조, True))

        dic_일별 = {m: dict() for m in LI_방식}
        for d in li_일자:
            dic_x = {m: dict(손익=0.0, 건수=0, 승=0, 손익1=0.0, 건1=0, 손익2=0.0, 건2=0,
                             튜닝=0, 대상=0) for m in LI_방식}
            n_롤, b_롤 = dic_롤조합[d]
            for code, (n_종, b_종) in dic_종조합[d].items():
                cell = dic['셀'][d][code]
                for m, n_조 in [('고정', self.n_현행), ('롤링', n_롤), ('종목별', n_종),
                               ('오라클', int(np.argmax(cell[:, 0])))]:
                    x, r = dic_x[m], cell[n_조]
                    x['손익'] += float(r[0]); x['건수'] += int(r[1]); x['승'] += int(r[2])
                    x['손익1'] += float(r[4]); x['건1'] += int(r[5])
                    x['손익2'] += float(r[6]); x['건2'] += int(r[7])
                    x['대상'] += 1
                dic_x['종목별']['튜닝'] += 1 if b_종 else 0
            dic_x['롤링']['튜닝'] = dic_x['롤링']['대상'] if b_롤 else 0
            for m in LI_방식:
                dic_일별[m][d] = dic_x[m]
        return li_일자, dic_일별, dic_종조합

    # =================================================================
    # 대조군: 전체 롤링 (하루 단위로 조합 하나 → 전 종목 적용)
    # =================================================================
    def 평가_전체롤링(self, dic, li_일자, n_학습창=N_학습창):
        """ 기존 롤링워크포워드와 같은 절차를 같은 행렬 위에서 재현 (선정종목만 합산) """
        dic_일합 = dict()
        for d in li_일자:
            dic_sel = dic['선정'].get(d, dict())
            a = np.zeros((len(self.li_조), N_셀))
            for code in dic_sel:
                if code in dic['셀'][d]:
                    a += dic['셀'][d][code]
            dic_일합[d] = a
        li_폴드 = list()
        for n_i in range(n_학습창, len(li_일자)):
            li_학습, d = li_일자[n_i - n_학습창:n_i], li_일자[n_i]
            a = np.stack([dic_일합[p] for p in li_학습])
            a_손익 = a[:, :, 0]
            b_유효 = a[:, :, 1].sum(axis=0) >= len(li_학습)
            if not b_유효.any():
                continue
            a_점수 = np.where(b_유효, -(a_손익 < -1e-9).sum(axis=0) * 1e6 + a_손익.sum(axis=0),
                            -np.inf)
            n_조 = int(np.argmax(a_점수))
            li_폴드.append(dict(검증일=d, 조합=n_조, 튜닝손익=float(dic_일합[d][n_조, 0]),
                              건수=int(dic_일합[d][n_조, 1]),
                              현행손익=float(dic_일합[d][self.n_현행, 0])))
        return li_폴드


def run(rebuild=False):
    z = 종목별롤링워크포워드()
    dic, li_일자, li_폴드, df_종목 = z.평가(rebuild=rebuild)
    li_불 = z.verify_행렬(dic, li_일자)
    print(f'\n대상 {len(li_일자)}일 / 충실도 불일치 {len(li_불)}일')
    for x in li_불:
        print(f'  {x[0]}: 시뮬 {x[1]:+.3f}%({x[2]}건) vs 원본 {x[3]:+.3f}%({x[4]}건)')

    print(f'\n{"=" * 108}')
    print(f'종목별 롤링워크포워드 — 조회창 {N_조회창}일 / 학습창 {N_학습창}일'
          f' / 최소학습건수 {N_최소학습건수}건 / 1순위 {S_목적} / 격자 {len(z.li_조)}칸')
    print('=' * 108)
    print(f'{"검증일":>9} | {"대상":>4} {"튜닝":>4} | {"하이브리드":>15} | {"현행":>13}'
          f' | {"튜닝분 효과":>11} | {"오라클":>9}')
    for x in li_폴드:
        print(f'{x["검증일"]:>9} | {x["대상"]:>4} {x["튜닝"]:>4} | '
              f'{x["하이브리드손익"]:>+8.2f}%({x["하이브리드건수"]:>3}건) | '
              f'{x["현행손익"]:>+8.2f}%({x["현행건수"]:>3}건) | '
              f'{x["튜닝분손익"] - x["튜닝분현행손익"]:>+9.2f}%p | {x["오라클손익"]:>+8.2f}%')
    n_효과 = sum(x['튜닝분손익'] - x['튜닝분현행손익'] for x in li_폴드)
    print('-' * 108)
    print(f'{"합계":>9} | {sum(x["대상"] for x in li_폴드):>4} '
          f'{sum(x["튜닝"] for x in li_폴드):>4} | '
          f'{sum(x["하이브리드손익"] for x in li_폴드):>+8.2f}%'
          f'({sum(x["하이브리드건수"] for x in li_폴드):>3}건) | '
          f'{sum(x["현행손익"] for x in li_폴드):>+8.2f}%'
          f'({sum(x["현행건수"] for x in li_폴드):>3}건) | '
          f'{n_효과:>+9.2f}%p | {sum(x["오라클손익"] for x in li_폴드):>+8.2f}%')
    print(f'  튜닝 적용 {sum(x["튜닝"] for x in li_폴드)}건(그중 현행 선택 '
          f'{sum(x["현행선택"] for x in li_폴드)}건) · 현행 회귀 '
          f'{sum(x["현행회귀"] for x in li_폴드)}건 · 무작위 대조 '
          f'{sum(x["무작위손익"] for x in li_폴드):+.2f}%')

    li_전체 = z.평가_전체롤링(dic, li_일자)
    li_공통 = [x['검증일'] for x in li_전체]
    print(f'\n[공통 검증구간 {li_공통[0]}~{li_공통[-1]} / {len(li_공통)}일] 세 방식 비교')
    n_하 = sum(x['하이브리드손익'] for x in li_폴드 if x['검증일'] in li_공통)
    n_현 = sum(x['현행손익'] for x in li_폴드 if x['검증일'] in li_공통)
    print(f'  하이브리드 {n_하:+.2f}% | 전체롤링 {sum(x["튜닝손익"] for x in li_전체):+.2f}%'
          f' | 현행 {n_현:+.2f}%')
    path = os.path.join(z.folder_백테, f'_종목별워크포워드_{pd.Timestamp.now():%Y%m%d_%H%M%S}.csv')
    df_종목.to_csv(path, index=False, encoding='utf-8-sig')
    print(f'\n종목·일자별 상세 저장: {path}')


if __name__ == '__main__':
    run(rebuild='--rebuild' in sys.argv)
