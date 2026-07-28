# -*- coding: utf-8 -*-
""" 틱기반매수세 전략 지표 탐색 도구 (제로베이스, 독립 실행)

    목적: "현행 지표에 무엇을 더할까"가 아니라, 백지에서 지표들을 동등하게 경쟁시켜
          '미래 상승을 실제로 예측하는' 지표를 데이터로 가려낸다.
          현행 진입지표(순매수비율·거래강도·체결속도·이격률 등)도 여러 후보 중 하나로 취급.

    방법:
      1) 선정종목 초당 1초봉에서 지표 목록(_지표목록) 전체를 계산
      2) 각 초의 미래성과(향후 N_미래창초 최대상승 MFE / 최대하락 MAE)를 붙임
      3) '유리'(= MFE>=트레일손익분기 & MAE>-손절, 그 자리 진입 시 승리 근사)를 라벨로
      4) 종목·날짜 내 순위로 통제한 뒤, 지표 상위구간의 유리율 리프트 + 날짜 일관성으로 랭킹
         → 리프트 높고 여러 날 일관된 지표만이 유효(한 날만 되면 과적합)

    확장: 새 지표 검토는 _지표목록에 함수 한 줄 추가 후 재실행하면 전체가 재평가된다.

    사용:
        python analyzer/지표탐색.py            # 패널 빌드(캐시) → 예측력 랭킹 리포트
        python analyzer/지표탐색.py --rebuild   # 패널 강제 재생성
"""
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 리포지토리 루트
import ut
from analyzer import bot_백테스팅_틱기반매수세 as BT   # 파라미터 재사용(손절·트레일·단주·선정필터)


# noinspection NonAsciiCharacters,PyPep8Naming,PyAttributeOutsideInit,SpellCheckingInspection
class IndicatorResearch:
    """ 제로베이스 지표 예측력 탐색 """

    N_미래창 = 1200        # 미래성과 창(초) = 20분
    N_샘플간격 = 15         # 샘플 간격(초) — 자기상관 완화
    N_상위분위 = 0.90         # 상위 10% 구간

    # ============================================================
    # 지표 목록 — 이름 -> frame(DataFrame) 받아 초당 값(Series) 반환
    # 여기 한 줄 추가하면 다음 실행부터 자동으로 랭킹에 포함된다.
    # frame 제공 컬럼: price, high, open, 매수량, 매도량, 틱수, 최대매수틱, 전체
    # ============================================================
    @staticmethod
    def _지표목록():
        def R(s, n):        # n초 롤링합
            return s.rolling(n).sum()

        dic_지표 = {
            # --- 현행 진입지표(후보로 동등 취급) ---
            '순매수비율': lambda f: R(f.매수량 - f.매도량, 60) / R(f.전체, 60).replace(0, np.nan),
            '거래강도': lambda f: R(f.전체, 60) / (R(f.전체, 300).shift(60) / 5).replace(0, np.nan),
            '체결속도': lambda f: R(f.틱수, 60) / (R(f.틱수, 300).shift(60) / 5).replace(0, np.nan),
            '덩어리배수': lambda f: f.최대매수틱.rolling(60).max()
                            / (R(f.전체, 300).shift(60) / R(f.틱수, 300).shift(60).replace(0, np.nan)).replace(0, np.nan),
            '이격률': lambda f: (f.high.shift(1) - f.price) / f.high.shift(1) * 100,
            # --- 모멘텀/가격작용 ---
            '모멘텀60': lambda f: (f.price / f.price.shift(60) - 1) * 100,
            '모멘텀300': lambda f: (f.price / f.price.shift(300) - 1) * 100,
            '가속도60': lambda f: (f.price / f.price.shift(60) - 1) * 100
                            - (f.price.shift(60) / f.price.shift(120) - 1) * 100,
            '범위내위치': lambda f: (f.price - f.price.rolling(300).min())
                            / (f.price.rolling(300).max() - f.price.rolling(300).min()).replace(0, np.nan),
            '시가대비': lambda f: (f.price / f.open - 1) * 100,
            # --- VWAP ---
            'vwap이격': lambda f: (f.price / ((f.price * f.전체).cumsum()
                            / f.전체.cumsum().replace(0, np.nan)) - 1) * 100,
            # --- 거래흐름 ---
            '매수서지': lambda f: R(f.매수량, 60) / (R(f.매수량, 300).shift(60) / 5).replace(0, np.nan),
            '매수매도비': lambda f: R(f.매수량, 60) / R(f.매도량, 60).replace(0, np.nan),
            '누적순매수기울기': lambda f: ((f.매수량 - f.매도량).cumsum()
                            - (f.매수량 - f.매도량).cumsum().shift(300)) / R(f.전체, 60).replace(0, np.nan),
            '틱불균형': lambda f: R((f.매수량 > 0).astype(float), 60)
                            / R((f.매수량 != 0) | (f.매도량 != 0), 60).replace(0, np.nan),
            # --- 변동성 ---
            '변동성확장': lambda f: (f.price.rolling(60).max() - f.price.rolling(60).min())
                            / (f.price.rolling(300).max() - f.price.rolling(300).min()).replace(0, np.nan),
        }
        return dic_지표

    def __init__(self):
        dic = ut.폴더manager.FolderManager().dic_폴더정보
        self.folder_틱 = dic['매수매도|주식체결']
        self.folder_백테 = os.path.join(dic['분석|백테스팅'], '클로드_틱기반매수세')
        self.folder_선정 = os.path.join(self.folder_백테, '10_종목선정')
        self.folder_캐시 = os.path.join(self.folder_백테, '_지표탐색캐시')
        os.makedirs(self.folder_캐시, exist_ok=True)
        self.s_틱시작일 = '20260716'
        self.n_장마감초 = 15 * 3600 + 15 * 60
        self.단주 = int(BT._T_단주)
        # 유리 라벨 기준: 트레일 손익분기 피크 이상 상승 & 손절 미만 하락
        self.n_손절 = float(BT._T_손절)
        self.n_트레일BE = ((1 + BT._T_비용 / 100) / (1 - BT._T_트레일 / 100) - 1) * 100
        self.li_지표명 = list(self._지표목록().keys())

    # ============================================================
    def _load_틱(self, s_일자):
        path = os.path.join(self.folder_틱, f'주식체결_{s_일자}.csv')
        if not os.path.exists(path):
            return None
        df = pd.read_csv(path, encoding='cp949', usecols=['종목코드', '체결시간', '현재가', '거래량', '고가'],
                         dtype=str, on_bad_lines='skip')
        for c in ['현재가', '고가']:
            df[c] = pd.to_numeric(df[c].str.replace('+', '', regex=False).str.replace('-', '', regex=False),
                                  errors='coerce')
        df['거래량'] = pd.to_numeric(df['거래량'], errors='coerce')
        df = df.dropna(subset=['현재가', '거래량', '고가'])
        df['종목코드'] = df['종목코드'].str.strip()
        s = df['체결시간'].str
        df['초'] = (pd.to_numeric(s[:2], errors='coerce') * 3600 + pd.to_numeric(s[2:4], errors='coerce') * 60
                   + pd.to_numeric(s[4:6], errors='coerce'))
        df = df.dropna(subset=['초'])
        df['초'] = df['초'].astype(int)
        return df[(df['초'] >= 9 * 3600) & (df['초'] <= 15 * 3600 + 30 * 60)]

    def _선정종목(self, s_일자):
        path = os.path.join(self.folder_선정, f'df_종목선정_{s_일자}.pkl')
        if not os.path.exists(path):
            return None
        df = pd.read_pickle(path)
        return df.loc[df['종목선정']]

    def li_일자(self):
        li = sorted(re.findall(r'\d{8}', f)[0] for f in os.listdir(self.folder_틱)
                    if '주식체결_' in f and '.csv' in f)
        return [d for d in li if d >= self.s_틱시작일]

    # ============================================================
    def _초당프레임(self, df_종목):
        """ 종목 하나 → 초당 1초봉 프레임(지표 계산 입력) """
        if len(df_종목) < 500:
            return None
        유효 = df_종목.loc[df_종목['거래량'].abs() > self.단주]
        매수틱 = 유효.loc[유효['거래량'] > 0]
        가격 = df_종목.groupby('초')['현재가'].last()
        s = np.arange(가격.index.min(), 가격.index.max() + 1)
        f = pd.DataFrame(index=s)
        f['price'] = 가격.reindex(s).ffill()
        f['high'] = df_종목.groupby('초')['고가'].last().reindex(s).ffill()
        f['open'] = f['price'].iloc[0]
        f['매수량'] = 매수틱.groupby('초')['거래량'].sum().reindex(s).fillna(0)
        f['매도량'] = (-유효.loc[유효['거래량'] < 0].groupby('초')['거래량'].sum()).reindex(s).fillna(0)
        f['틱수'] = 유효.groupby('초')['거래량'].size().reindex(s).fillna(0)
        f['최대매수틱'] = 매수틱.groupby('초')['거래량'].max().reindex(s).fillna(0)
        f['전체'] = f['매수량'] + f['매도량']
        return f

    @staticmethod
    def _미래극값(price, W_fwd):
        """ 각 t의 향후 [t+1,t+W] 최대/최소 (원본 정렬) """
        fut = pd.Series(price).shift(-1)
        rev = fut[::-1]
        fmax = rev.rolling(W_fwd, min_periods=1).max()[::-1].values
        fmin = rev.rolling(W_fwd, min_periods=1).min()[::-1].values
        return fmax, fmin

    # ============================================================
    def make_패널(self, rebuild=False):
        path = os.path.join(self.folder_캐시, 'panel.pkl')
        if os.path.exists(path) and not rebuild:
            return pd.read_pickle(path)
        dic_지표 = self._지표목록()
        rows = []
        for day in self.li_일자():
            df_틱 = self._load_틱(day)
            df_sel = self._선정종목(day)
            if df_틱 is None or df_sel is None or df_sel.empty:
                continue
            codes = df_sel['종목코드'].tolist()
            n = 0
            for code, g in df_틱[df_틱['종목코드'].isin(codes)].groupby('종목코드', sort=False):
                f = self._초당프레임(g)
                if f is None:
                    continue
                n += 1
                for name, fn in dic_지표.items():
                    f[name] = fn(f).values
                fmax, fmin = self._미래극값(f['price'].values, self.N_미래창)
                f['미래최대상승'] = (fmax / f['price'].values - 1) * 100
                f['미래최대하락'] = (fmin / f['price'].values - 1) * 100
                s = f.index.values
                sel = ((s > s[0] + 360) & (s < self.n_장마감초 - 60) & ((s - s[0]) % self.N_샘플간격 == 0))
                sub = f.loc[sel, self.li_지표명 + ['미래최대상승', '미래최대하락']].copy()
                sub['일자'] = day
                sub['종목코드'] = code
                rows.append(sub)
            print(f'{day}: {n}종목')
        panel = pd.concat(rows).reset_index(drop=True).dropna(subset=['미래최대상승', '미래최대하락'])
        pd.to_pickle(panel, path)
        return panel

    # ============================================================
    def calc_예측력(self, panel):
        panel = panel.copy()
        panel['유리'] = ((panel['미래최대상승'] >= self.n_트레일BE) & (panel['미래최대하락'] > -self.n_손절)).astype(int)
        base = panel['유리'].mean()
        g = panel.groupby(['일자', '종목코드'])
        n_days = panel['일자'].nunique()
        res = []
        for f in self.li_지표명:
            panel['_r'] = g[f].rank(pct=True)
            top = panel[panel['_r'] >= self.N_상위분위]
            tr = top['유리'].mean()
            lift = tr / base if base > 0 else np.nan
            # 양방향(상/하위) 중 강한 쪽 표시 — 제로베이스라 방향도 데이터가 결정
            bot = panel[panel['_r'] <= 1 - self.N_상위분위]
            brate = bot['유리'].mean()
            b_상위방향 = tr >= brate
            best_rate, best_lift = (tr, lift) if b_상위방향 else (brate, brate / base if base > 0 else np.nan)
            n_일관일수 = sum(
                (panel[(panel['일자'] == d) & (panel['_r'] >= self.N_상위분위)]['유리'].mean() if b_상위방향
                 else panel[(panel['일자'] == d) & (panel['_r'] <= 1 - self.N_상위분위)]['유리'].mean())
                > panel[panel['일자'] == d]['유리'].mean()
                for d in panel['일자'].unique())
            res.append(dict(지표=f, 방향='상위' if b_상위방향 else '하위', 유리율=best_rate * 100,
                            리프트=best_lift, MFE=top['미래최대상승'].mean(), MAE=top['미래최대하락'].mean(),
                            일관성=f'{n_일관일수}/{n_days}', n_일관일수=n_일관일수))
        df = pd.DataFrame(res).sort_values('리프트', ascending=False).reset_index(drop=True)
        return df, base

    # ============================================================
    def run(self, rebuild=False):
        panel = self.make_패널(rebuild=rebuild)
        df, base = self.calc_예측력(panel)
        cur = ['순매수비율', '거래강도', '체결속도', '덩어리배수', '이격률']
        li = []
        li.append(f'관측 {len(panel):,} | 기저 유리율 {base*100:.2f}% '
                  f'(유리 = 향후{self.N_미래창//60}분 최대상승>={self.n_트레일BE:.2f}% & 최대하락>-{self.n_손절:.2f}%)')
        li.append(f'지표 {len(self.li_지표명)}종 — 현행 진입지표도 후보로 동등 평가 (◆=현행)')
        li.append('')
        li.append(f'{"지표":>11} | {"방향":>4} | {"유리율":>6} | {"리프트":>5} | {"상위MFE":>7} | {"상위MAE":>7} | {"일관성":>5}')
        li.append('-' * 74)
        for _, r in df.iterrows():
            mark = '◆' if r['지표'] in cur else ' '
            li.append(f'{mark}{r["지표"]:>10} | {r["방향"]:>4} | {r["유리율"]:>5.2f}% | {r["리프트"]:>5.2f} '
                      f'| {r["MFE"]:>6.2f}% | {r["MAE"]:>6.2f}% | {r["일관성"]:>5}')
        li.append('-' * 74)
        n_days = panel['일자'].nunique()
        유효 = df[(df['리프트'] >= 1.3) & (df['n_일관일수'] >= n_days - 1)]
        li.append(f'유효 후보(리프트>=1.3 & 일관성>={n_days-1}/{n_days}): '
                  + (', '.join(f'{r.지표}({r.방향},리프트{r.리프트:.2f})' for r in 유효.itertuples()) if len(유효) else '없음'))
        li.append('')
        li.append('※ 리프트 낮음 = 그 지표 단독 예측력 없음. 유효 후보만 백테스트/워크포워드로 검증할 것.')
        li.append('※ 새 지표 검토: 이 파일 _지표목록에 함수 추가 후 --rebuild 재실행.')
        txt = '\n'.join(li)
        print(txt)
        out = os.path.join(self.folder_백테, f'_지표탐색리포트_{pd.Timestamp.now():%Y%m%d_%H%M%S}.txt')
        with open(out, 'w', encoding='utf-8') as fp:
            fp.write(txt)
        print(f'\n리포트 저장: {out}')


def run():
    """ 실행 함수 """
    IndicatorResearch().run(rebuild='--rebuild' in sys.argv)


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print('\n### [ KeyboardInterrupt detected ] ###')
