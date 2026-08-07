# -*- coding: utf-8 -*-
""" 롤링 워크포워드 — 직전 N일 학습 → 다음 1일 검증, 하루씩 이동 (독립 실행 / 대시보드 호출)

    목적: "지금 파라미터를 그대로 두는 것"과 "매일 직전 N일로 다시 최적화하는 것" 중
          어느 쪽이 미지의 다음 날에 나았는지를 누적으로 보여준다.

    현행과의 차이는 진입 조건 축뿐이고 청산·구간2·자금관리는 전부 현행 그대로다.
    탐색 축에는 워크포워드검증.LI_후보지표 로 등록된 미사용 지표가 포함된다
    (문턱 0 = 그 축 미사용이므로 현행 조합도 격자 안에 들어 있다).

    비교 기준 셋
      튜닝   : 직전 N일 학습셋에서 고른 조합을 검증일에 적용
      현행   : 지금 쓰는 파라미터 (튜닝 없음)
      오라클 : 그 검증일을 미리 알았을 때의 최선 (달성 불가능한 상한)
      + 무작위: 격자에서 아무거나 골랐을 때의 평균 — 튜닝이 정보를 쓴 것인지 가리는 대조군

    손익행렬(조합×일자)을 캐시에 쌓고 새 일자만 증분 계산한다.
    (매일 대시보드에서 호출되므로 전량 재계산하면 안 된다)

    사용:
        python analyzer/롤링워크포워드.py            # 증분 계산 → 리포트 출력
        python analyzer/롤링워크포워드.py --rebuild   # 손익행렬 전량 재계산
"""
import os
import sys
import itertools

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyzer.워크포워드검증 import WalkForward
from analyzer import bot_백테스팅_틱기반매수세 as BT

N_학습창 = 10                                   # 직전 N일 학습 (10일창이 가장 안정적임을 확인)
S_행렬파일 = '_롤링손익행렬.pkl'

# 탐색 축 — 구간1 진입만. 문턱 0 / False = 그 축 미사용(현행)
DIC_탐색 = dict(
    구간1체결률=[5.0, 7.0, 9.0],
    구간1트레일=[1.5, 2.0, 2.5],
    강도문턱=[0.0, 100.0, 120.0],               # 체결강도 1분롤링 하한
    누적비교=[False, True],                      # 체결강도 1분롤링 > 당일 누적
    횟수강도문턱=[0.0, 100.0],                   # 체결횟수강도 1분롤링 하한
    단위비=[0.0, 1.0],                           # 단위매수량 ÷ 단위매도량 하한
    매수횟수5문턱=[0.0, 7.0, 10.0],              # 매수횟수 5초 이동평균 하한
)


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection
class 롤링워크포워드(WalkForward):
    """ 구간1+구간2 를 한 포지션 북에서 돌리고, 구간1 진입에 후보지표 필터를 얹는다 """

    def __init__(self):
        super().__init__()
        self.n_구간1시작 = 9 * 3600
        self.n_구간1종료 = 9 * 3600 + BT._구간1_종료
        self.path_행렬 = os.path.join(self.folder_캐시, S_행렬파일)
        self.dic_현행파라미터.update(
            구간1사용=bool(BT._구간1_사용), 구간1체결률=BT._구간1_체결률,
            구간1순매수=BT._구간1_순매수, 구간1창=BT._구간1_창, 구간1상승창=BT._구간1_상승창,
            구간1트레일=BT._구간1_트레일, 구간1손절=BT._구간1_손절,
            구간1최대보유=BT._구간1_최대보유, 구간1쿨다운=BT._구간1_쿨다운,
            구간1일최대=BT._구간1_일최대,
            강도문턱=0.0, 누적비교=False, 횟수강도문턱=0.0, 단위비=0.0, 매수횟수5문턱=0.0)

    # =================================================================
    # 시뮬 (원본 _make_거래_종목 거래 루프 — 구간1+구간2 단일 포지션 북)
    # =================================================================
    @staticmethod
    def _후보지표마스크(arr, P):
        """ 등록된 미사용 지표로 만든 진입 필터. 전 축이 미사용이면 all-True """
        b = np.ones(len(arr['ary_초']), dtype=bool)
        if P.get('강도문턱', 0) > 0:
            b &= np.nan_to_num(arr['체결강도롤링'], nan=0.0) >= P['강도문턱']
        if P.get('누적비교', False):
            b &= (np.nan_to_num(arr['체결강도롤링'], nan=0.0)
                  > np.nan_to_num(arr['체결강도누적'], nan=np.inf))
        if P.get('횟수강도문턱', 0) > 0:
            b &= np.nan_to_num(arr['체결횟수강도롤링'], nan=0.0) >= P['횟수강도문턱']
        if P.get('단위비', 0) > 0:
            a_도 = np.nan_to_num(arr['단위매도량'], nan=0.0)
            a_비 = np.divide(np.nan_to_num(arr['단위매수량'], nan=0.0), a_도,
                            out=np.zeros_like(a_도), where=a_도 > 0)
            b &= a_비 >= P['단위비']
        if P.get('매수횟수5문턱', 0) > 0:
            b &= np.nan_to_num(arr['매수횟수5'], nan=0.0) >= P['매수횟수5문턱']
        return b

    def _sim_종목(self, arr, s_일자, code, P):
        ary_초, ary_가격 = arr['ary_초'], arr['price']
        n_길이 = len(ary_초)

        n_웜업 = ary_초[0] + 360
        ary_진입 = ((arr['순매수비율'] > P['순매수비율']) & (arr['거래강도'] > P['거래강도'])
                  & (arr['전체60'] >= P['최소거래량'])
                  & (arr['체결속도'] >= P['체결속도']) & (arr['덩어리배수'] <= P['덩어리상한'])
                  & (ary_초 > n_웜업) & (ary_초 < self.n_장마감초)
                  & (ary_초 >= (self.n_구간1종료 if P['구간1사용'] else 0))
                  & (arr['이격률'] >= P['이격최소']) & (arr['이격률'] < P['이격최대']))
        ary_진입 = np.nan_to_num(ary_진입, nan=False).astype(bool)

        if P['구간1사용']:
            n_창 = int(P['구간1창'])
            sri_매수, sri_매도 = pd.Series(arr['매수량']), pd.Series(arr['매도량'])
            a_체결률 = (pd.Series(arr['매수틱수']).rolling(n_창).sum() / n_창).values
            a_순매수 = ((sri_매수 - sri_매도).rolling(n_창).sum()
                     / (sri_매수 + sri_매도).rolling(n_창).sum().replace(0, np.nan)).values
            a_상승 = pd.Series(ary_가격).gt(
                pd.Series(ary_가격).shift(int(P['구간1상승창']))).values
            ary_g1 = np.nan_to_num(
                ((a_체결률 >= P['구간1체결률']) & a_상승 & (a_순매수 >= P['구간1순매수'])
                 & (ary_초 >= self.n_구간1시작) & (ary_초 < self.n_구간1종료)),
                nan=False).astype(bool)
            ary_g1 &= self._후보지표마스크(arr, P)
        else:
            ary_g1 = np.zeros(n_길이, dtype=bool)

        idx_후보, idx_g1 = np.where(ary_진입)[0], np.where(ary_g1)[0]
        li = list()
        i, n_횟수1, n_횟수2 = 0, 0, 0
        while True:
            i1 = (int(idx_g1[np.searchsorted(idx_g1, i)])
                  if n_횟수1 < P['구간1일최대'] and np.searchsorted(idx_g1, i) < len(idx_g1)
                  else n_길이)
            i2 = (int(idx_후보[np.searchsorted(idx_후보, i)])
                  if n_횟수2 < P['일최대거래'] and np.searchsorted(idx_후보, i) < len(idx_후보)
                  else n_길이)
            if min(i1, i2) >= n_길이:
                break
            b_g1 = i1 <= i2
            i_진입 = i1 if b_g1 else i2
            n_손절률 = P['구간1손절'] if b_g1 else P['손절']
            n_트레일률 = P['구간1트레일'] if b_g1 else P['트레일']
            n_최대보유 = P['구간1최대보유'] if b_g1 else P['최대보유']
            n_쿨다운 = P['구간1쿨다운'] if b_g1 else P['쿨다운']
            n_매수가 = ary_가격[i_진입] * (1 + BT._T_매수슬립 / 100)
            n_손절가 = n_매수가 * (1 - n_손절률 / 100)

            i_시작 = i_진입 + 1
            ary_구간 = ary_가격[i_시작:]
            if len(ary_구간) == 0:
                break
            ary_피크 = np.maximum.accumulate(np.concatenate(([n_매수가], ary_구간)))[1:]
            ary_스탑 = np.maximum(n_손절가, ary_피크 * (1 - n_트레일률 / 100))
            if P['본전발동'] > 0 and not b_g1:
                n_본전가 = n_매수가 * (1 + P['비용'] / 100) / (1 - BT._T_매도슬립 / 100)
                ary_스탑 = np.where(ary_피크 >= n_매수가 * (1 + P['본전발동'] / 100),
                                   np.maximum(ary_스탑, n_본전가), ary_스탑)
            ary_터치 = ary_구간 <= ary_스탑
            i_스탑 = int(np.argmax(ary_터치)) if ary_터치.any() else n_길이
            i_마감 = int(np.searchsorted(ary_초[i_시작:], self.n_장마감초))
            i_마감 = i_마감 if i_마감 < len(ary_구간) else n_길이
            i_보유초과 = n_최대보유 - 1
            i_청산상대 = min(i_스탑, i_마감, i_보유초과)
            if i_청산상대 >= n_길이 or i_시작 + i_청산상대 >= n_길이:
                i_청산, s_사유 = n_길이 - 1, '타임아웃'
            else:
                i_청산 = i_시작 + i_청산상대
                s_사유 = (('손절터치' if ary_스탑[i_스탑] == n_손절가 else '트레일청산')
                        if i_청산상대 == i_스탑
                        else '보유초과' if i_청산상대 == i_보유초과 else '타임아웃')
            n_매도가 = (min(ary_스탑[i_청산상대], ary_가격[i_청산])
                     if s_사유 in ['손절터치', '트레일청산'] else ary_가격[i_청산])
            n_매도가 *= (1 - BT._T_매도슬립 / 100)

            li.append(dict(일자=s_일자, 종목코드=code,
                           매수초=int(ary_초[i_진입]), 매도초=int(ary_초[i_청산]),
                           매수가=n_매수가, 매도가=n_매도가,
                           수익률=(n_매도가 / n_매수가 - 1) * 100 - P['비용'], 사유=s_사유,
                           구간=('구간1' if b_g1 else '구간2')))
            if b_g1:
                n_횟수1 += 1
            else:
                n_횟수2 += 1
            i = i_청산 + n_쿨다운
        return li

    def verify(self, li_일자, caches):
        """ 충실도 게이트 — 구간1+구간2 를 함께 돌리므로 '전건' 일치를 본다

            부모 verify 는 구간2만 복제하는 도구여서 30_거래내역에서 구간2만 골라 비교한다.
            이 클래스는 두 구간을 한 포지션 북에서 돌리므로 그대로 쓰면 항상 불일치가 난다
            (구간1 포지션이 09:10을 넘겨 유지되면 구간2 진입을 막기 때문에도 함께 돌려야 맞다). """
        li_불일치 = list()
        for d in li_일자:
            li = self.sim_day(caches[d], d, self.dic_현행파라미터)
            new = sorted((t['종목코드'], round(t['매수가'], 1), round(t['수익률'], 3)) for t in li)
            path = os.path.join(self.folder_거래, f'df_거래내역_{d}.pkl')
            if not os.path.exists(path):
                continue
            df = pd.read_pickle(path)
            if not len(df):
                old = []
            else:
                df = df.copy()
                df['종목코드'] = df['종목코드'].astype(str).str.strip()
                old = sorted((r['종목코드'], round(r['매수가'], 1), round(r['수익률'], 3))
                             for _, r in df.iterrows())
            if new != old:
                li_불일치.append((d, new, old))
        return li_불일치

    # =================================================================
    # 손익행렬 (조합 × 일자) — 새 일자만 증분
    # =================================================================
    @staticmethod
    def li_조합():
        li_키 = list(DIC_탐색.keys())
        return li_키, list(itertools.product(*[DIC_탐색[k] for k in li_키]))

    def 행렬갱신(self, rebuild=False, li_일자=None, caches=None):
        """ {조합번호: {일자: (손익, 건수)}} 를 갱신해 반환 """
        li_키, li_조 = self.li_조합()
        dic_행렬 = dict()
        if os.path.exists(self.path_행렬) and not rebuild:
            try:
                dic_저장 = pd.read_pickle(self.path_행렬)
                if dic_저장.get('탐색') == DIC_탐색:      # 축이 바뀌면 캐시 폐기
                    dic_행렬 = dic_저장.get('행렬', dict())
            except (OSError, EOFError, KeyError, ValueError):
                dic_행렬 = dict()

        if li_일자 is None:
            li_일자, caches = self.load_caches()
            li_일자 = [d for d in li_일자 if caches[d]]

        li_신규 = [d for d in li_일자
                 if any(d not in dic_행렬.get(i, dict()) for i in range(len(li_조)))]
        if li_신규:
            P현행 = dict(self.dic_현행파라미터)
            for i, vals in enumerate(li_조):
                P = dict(P현행); P.update(dict(zip(li_키, vals)))
                row = dic_행렬.setdefault(i, dict())
                for d in li_신규:
                    if d in row:
                        continue
                    li_t = self.sim_day(caches[d], d, P)
                    row[d] = (float(sum(t['수익률'] for t in li_t)), len(li_t))
            pd.to_pickle(dict(탐색=DIC_탐색, 행렬=dic_행렬), self.path_행렬)
        return dic_행렬, li_일자, caches, li_신규

    # =================================================================
    # 평가
    # =================================================================
    @staticmethod
    def _학습점수(row, li_학습):
        """ 워크포워드검증과 동일 목적함수: (-손실일수, 총손익), 무거래 퇴행 배제 """
        li_p = [row[d][0] for d in li_학습]
        if sum(row[d][1] for d in li_학습) < len(li_학습):
            return None
        return (-sum(1 for p in li_p if p < -1e-9), sum(li_p))

    def 평가(self, n_학습창=N_학습창, rebuild=False):
        """ 폴드 리스트 + 합계 + 대조군을 돌려준다 (실패 시 None) """
        dic_행렬, li_일자, caches, _ = self.행렬갱신(rebuild=rebuild)
        if len(li_일자) <= n_학습창:
            return None
        li_키, li_조 = self.li_조합()
        i_현행 = next((i for i, v in enumerate(li_조)
                     if dict(zip(li_키, v)) == {k: self.dic_현행파라미터[k] for k in li_키}), None)

        li_폴드 = list()
        for n_i in range(n_학습창, len(li_일자)):
            li_학습, d = li_일자[n_i - n_학습창:n_i], li_일자[n_i]
            n_best, t_best = None, None
            for i in range(len(li_조)):
                s = self._학습점수(dic_행렬[i], li_학습)
                if s is None:
                    continue
                if t_best is None or s > t_best:
                    t_best, n_best = s, i
            if n_best is None:
                continue
            n_현행 = (dic_행렬[i_현행][d][0] if i_현행 is not None
                    else sum(t['수익률'] for t in
                             self.sim_day(caches[d], d, self.dic_현행파라미터)))
            li_폴드.append(dict(
                검증일=d, 학습=li_학습, 튜닝=dic_행렬[n_best][d][0], 건수=dic_행렬[n_best][d][1],
                현행=n_현행, 오라클=max(dic_행렬[i][d][0] for i in range(len(li_조))),
                파라미터=dict(zip(li_키, li_조[n_best]))))
        if not li_폴드:
            return None

        li_검증 = [r['검증일'] for r in li_폴드]
        a_칸합 = np.array([sum(dic_행렬[i][d][0] for d in li_검증) for i in range(len(li_조))])
        n_튜닝 = sum(r['튜닝'] for r in li_폴드)
        return dict(
            폴드=li_폴드, 학습창=n_학습창, 조합수=len(li_조),
            튜닝=n_튜닝, 현행=sum(r['현행'] for r in li_폴드),
            오라클=sum(r['오라클'] for r in li_폴드),
            무작위=float(a_칸합.mean()), 무작위중앙=float(np.median(a_칸합)),
            튜닝백분위=100 - float((a_칸합 < n_튜닝).mean() * 100),
            승=sum(1 for r in li_폴드 if r['튜닝'] > r['현행']),
            동일=sum(1 for r in li_폴드 if abs(r['튜닝'] - r['현행']) < 1e-9))

    @staticmethod
    def s_파라미터(dic_p):
        """ 폴드가 고른 조합을 사람이 읽는 문자열로 """
        li = [f'체결률 {dic_p["구간1체결률"]:.0f}', f'트레일 {dic_p["구간1트레일"]:.1f}']
        if dic_p.get('강도문턱'):
            li.append(f'강도≥{dic_p["강도문턱"]:.0f}')
        if dic_p.get('누적비교'):
            li.append('누적비교')
        if dic_p.get('횟수강도문턱'):
            li.append(f'횟수강도≥{dic_p["횟수강도문턱"]:.0f}')
        if dic_p.get('단위비'):
            li.append(f'단위비≥{dic_p["단위비"]:.1f}')
        if dic_p.get('매수횟수5문턱'):
            li.append(f'매수5≥{dic_p["매수횟수5문턱"]:.0f}')
        return ' · '.join(li)


def run(rebuild=False):
    wf = 롤링워크포워드()
    li_d, caches = wf.load_caches()
    li_d = [d for d in li_d if caches[d]]
    li_불 = wf.verify(li_d, caches)
    print(f'대상 {len(li_d)}일 / 충실도 불일치 {len(li_불)}일')
    if li_불:
        print('★ 충실도 검증 실패 — 결과 신뢰 불가')
        return

    for n_창 in [5, 7, 10]:
        r = wf.평가(n_학습창=n_창, rebuild=(rebuild and n_창 == 5))
        if r is None:
            print(f'\n[학습창 {n_창}일] 폴드 없음')
            continue
        print(f'\n{"=" * 104}')
        print(f'학습창 {n_창}일 — 폴드 {len(r["폴드"])}개 / 격자 {r["조합수"]}칸')
        print('=' * 104)
        print(f'{"검증일":>9} | {"튜닝":>13} | {"현행":>9} | {"오라클":>9} | 채택')
        for x in r['폴드']:
            print(f'{x["검증일"]:>9} | {x["튜닝"]:>+8.2f}%({x["건수"]:>2}건) | {x["현행"]:>+8.2f}% '
                  f'| {x["오라클"]:>+8.2f}% | {wf.s_파라미터(x["파라미터"])}')
        print('-' * 104)
        print(f'{"합계":>9} | {r["튜닝"]:>+8.2f}%       | {r["현행"]:>+8.2f}% | {r["오라클"]:>+8.2f}% |')
        print(f'  튜닝 우세 {r["승"]}/{len(r["폴드"])}일 · 현행과 동일선택 {r["동일"]}일 · '
              f'무작위 평균 {r["무작위"]:+.2f}% · 튜닝 상위 {r["튜닝백분위"]:.0f}%')


if __name__ == '__main__':
    run(rebuild='--rebuild' in sys.argv)
