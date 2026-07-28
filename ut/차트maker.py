import os
import sys

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, FuncFormatter


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection,PyUnreachableCode
class ChartMaker:
    def __init__(self):
        # 기준폴더 정의
        self.folder_베이스 = os.path.dirname(os.path.abspath(__file__))
        self.folder_프로젝트 = os.path.dirname(self.folder_베이스)

        # 구동 os 확인
        dic_운영체제 = dict(darwin='mac', win32='win', linux='linux')
        self.s_운영체제 = dic_운영체제[sys.platform]

        # 그래프 한글 설정
        from matplotlib import font_manager
        path_font = 'c:/Windows/Fonts/malgun.ttf' if self.s_운영체제 == 'win' else\
                    '/System/Library/Fonts/Supplemental/AppleGothic.ttf' if self.s_운영체제 == 'mac' else None
        font_name = font_manager.FontProperties(fname=path_font).get_name()
        plt.rcParams['font.family'] = font_name
        plt.rcParams['axes.unicode_minus'] = False

        # 차트 색상코드 정의 - 기본색상코드
        self.dic_색상 = dict(파랑='C0', 주황='C1', 녹색='C2', 빨강='C3', 보라='C4',
                           고동='C5', 분홍='C6', 회색='C7', 올리브='C8', 하늘='C9')

    def ax_누적기대치(self, ax, df_매매일보, n_기준예수금=None):
        """ 입력된 데이터 기준으로 기대수익 그래프 생성 후 리턴 """
        # 데이터 정의
        li_일자 = [f'{일자[4:6]}-{일자[6:8]}' for 일자 in df_매매일보['일자']]
        ary_일간매매 = df_매매일보['일간매매'].values
        ary_일간수익매매 = df_매매일보['일간수익매매'].values
        ary_일간손실매매 = df_매매일보['일간손실매매'].values
        ary_일간승률 = df_매매일보['일간승률'].values
        ary_일간손익비 = df_매매일보['일간손익비'].values
        ary_일간기대치 = df_매매일보['일간기대치'].values
        ary_주간기대치 = df_매매일보['주간기대치'].values
        ary_누적매매 = df_매매일보['누적매매'].values
        ary_누적수익매매 = df_매매일보['누적수익매매'].values
        ary_누적손실매매 = df_매매일보['누적손실매매'].values
        ary_누적승률 = df_매매일보['누적승률'].values / 100
        ary_누적손익비 = df_매매일보['누적손익비'].values
        ary_누적기대치 = df_매매일보['누적기대치'].values

        # 그래프 설정
        ax_메인축 = ax
        ax_보조축 = ax.twinx()
        # 기대치 (일간기대치 막대는 거래후예수금 막대로 대체 - 아래 예수금 블록에서 표시)
        ax_메인축.plot(li_일자, ary_주간기대치, label='주간기대치', lw=2, alpha=0.5, color=self.dic_색상['분홍'])
        ax_메인축.plot(li_일자, ary_누적기대치, label='누적기대치', lw=2, alpha=1, color=self.dic_색상['주황'])
        ax_메인축.axhline(0.2, lw=2, alpha=0.5, linestyle='--', color=self.dic_색상['주황'])
        # 승률
        ax_메인축.plot(li_일자, ary_누적승률, label='누적승률', lw=2, alpha=1, color=self.dic_색상['녹색'])
        ax_메인축.axhline(0.3, lw=2, alpha=0.5, linestyle='--', color=self.dic_색상['녹색'])
        # 손익비
        ax_보조축.plot(li_일자, ary_누적손익비, label='누적손익비', lw=2, alpha=1, color=self.dic_색상['보라'])
        ax_보조축.axhline(3, lw=2, alpha=0.5, linestyle='--', color=self.dic_색상['보라'])

        # 스케일 설정
        ax_메인축.set_ylim(-1.2, 1.2)
        li_틱 = [-1.2, -0.8, -0.4, 0, 0.4, 0.8, 1.2]
        ax_메인축.set_yticks(li_틱, labels=[f'{틱:,.2f}' if 틱 not in [li_틱[0], li_틱[-1]] else '' for 틱 in li_틱])
        # 보조축
        ax_보조축.set_ylim(-1, 5)
        # li_틱 = [-1, 0, 1, 2, 3, 4, 5]
        li_틱 = [-9, -6, -3, 0, 3, 6, 9]
        ax_보조축.set_yticks(li_틱, labels=[f'{틱:,.1f}' if 틱 not in [li_틱[0], li_틱[-1]] else '' for 틱 in li_틱])
        # ax_메인축.autoscale(enable=True, axis='both', tight=False)
        # ax_메인축.yaxis.set_major_locator(MaxNLocator(nbins=6, integer=False))
        # ax_메인축.margins(x=0.05, y=0.05)
        # ax_보조축.autoscale(enable=True, axis='both', tight=False)
        # ax_보조축.yaxis.set_major_locator(MaxNLocator(nbins=6, integer=False))
        # ax_보조축.margins(x=0.05, y=0.05)

        # 뷰 설정
        ax_메인축.set_title('[ 기대치 ]', loc='left', fontsize=10, fontweight='bold')
        ax_메인축.grid(True, axis='y', color='gray', linestyle='--', linewidth=0.5, alpha=0.5)
        ax_메인축.legend(loc='upper left', fontsize=8)
        ax_메인축.set_xticks([li_일자[0], li_일자[-1]])
        ax_메인축.tick_params(length=0, labelsize=8)
        ax_보조축.tick_params(length=0, labelsize=8)
        ax_메인축.axhline(0, lw=0.5, alpha=1, color='black')
        ax_보조축.axhline(0, lw=0.5, alpha=1, color='black')

        # 텍스트 설정
        n_누적기대치 = ary_누적기대치[-1]
        n_누적승률 = ary_누적승률[-1] * 100
        n_누적손익비 = ary_누적손익비[-1]
        n_누적매매 = ary_누적매매[-1]
        # ax_메인축.text(0.99, 0.97, f'기대치 {n_누적기대치:,.2f}', fontsize=9, fontweight='bold', color=self.dic_색상['주황'],
        #             va='top', ha='right', transform=ax_메인축.transAxes)
        # ax_메인축.text(0.99, 0.90, f'승률 {n_누적승률:,.0f}%', fontsize=9, fontweight='bold', color=self.dic_색상['녹색'],
        #             va='top', ha='right', transform=ax_메인축.transAxes)
        # ax_메인축.text(0.99, 0.83, f'손익비 {n_누적손익비:,.1f}', fontsize=9, fontweight='bold', color=self.dic_색상['보라'],
        #             va='top', ha='right', transform=ax_메인축.transAxes)
        # ax_메인축.text(0.99, 0.76, f'매매수 {n_누적매매:,.0f}', fontsize=9, fontweight='bold', color=self.dic_색상['회색'],
        #             va='top', ha='right', transform=ax_메인축.transAxes)
        ax_메인축.text(0.68, 0.98, f'기대치 {n_누적기대치:,.2f}', fontsize=9, fontweight='bold', color=self.dic_색상['주황'],
                    va='top', ha='left', transform=ax_메인축.transAxes)
        ax_메인축.text(0.68, 0.91, f'손익비 {n_누적손익비:,.1f}', fontsize=9, fontweight='bold', color=self.dic_색상['보라'],
                    va='top', ha='left', transform=ax_메인축.transAxes)
        ax_메인축.text(0.85, 0.98, f'승률 {n_누적승률:,.0f}%', fontsize=9, fontweight='bold', color=self.dic_색상['녹색'],
                    va='top', ha='left', transform=ax_메인축.transAxes)
        ax_메인축.text(0.85, 0.91, f'매매 {n_누적매매:,.0f}', fontsize=9, fontweight='bold', color=self.dic_색상['회색'],
                    va='top', ha='left', transform=ax_메인축.transAxes)

        # 거래후예수금 (예수금 기반 리스크 사이징 - 해당 컬럼이 있는 전략에서만 표시)
        # 꺾은선 = 거래후예수금(기준예수금 정중앙) / 회색 막대 = 일별 손익 (0 원점 - 위=수익, 아래=손실)
        if '거래후예수금' in df_매매일보.columns:
            ary_거래후예수금 = df_매매일보['거래후예수금'].values.astype(float)
            n_기준 = float(n_기준예수금) if n_기준예수금 is not None else float(ary_거래후예수금[0])

            # 일별 손익 막대 (전일 거래후예수금 대비 증감, 첫날은 기준예수금 대비)
            li_일별손익 = [예수금 - 전일 for 예수금, 전일 in zip(ary_거래후예수금, [n_기준] + list(ary_거래후예수금[:-1]))]
            ax_손익 = ax.twinx()
            n_손익최대 = max(max(abs(손익) for 손익 in li_일별손익), 1.0)
            ax_손익.set_ylim(-n_손익최대 * 1.15, n_손익최대 * 1.15)   # 0을 정중앙(원점)에 - 메인축 0선과 정렬
            ax_손익.bar(li_일자, li_일별손익, label='일별손익', alpha=0.4, color=self.dic_색상['회색'])
            ax_손익.set_yticks([])
            ax_손익.set_zorder(ax_메인축.get_zorder() - 1)   # 막대를 라인 뒤로 (배경)
            ax_메인축.patch.set_visible(False)              # 메인축 배경이 막대를 가리지 않도록

            # 거래후예수금 꺾은선 - 초기자본(기준예수금)을 y축 정중앙으로 고정 (위=수익, 아래=손실)
            ax_예수금 = ax.twinx()
            ax_예수금.spines['right'].set_position(('outward', 42))
            ax_예수금.plot(li_일자, ary_거래후예수금, label='거래후예수금', lw=2, alpha=0.9, color=self.dic_색상['파랑'])
            n_편차 = max(abs(ary_거래후예수금.max() - n_기준), abs(ary_거래후예수금.min() - n_기준), n_기준 * 0.01)
            ax_예수금.set_ylim(n_기준 - n_편차 * 1.15, n_기준 + n_편차 * 1.15)   # 기준을 정중앙(원점)에
            ax_예수금.axhline(n_기준, lw=1, ls='--', alpha=0.6, color=self.dic_색상['파랑'])
            ax_예수금.set_yticks([n_기준 - n_편차, n_기준, n_기준 + n_편차])
            ax_예수금.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x / 1e4:,.0f}만'))
            ax_예수금.tick_params(length=0, labelsize=7)
            h_손익, l_손익 = ax_손익.get_legend_handles_labels()
            h_예수금, l_예수금 = ax_예수금.get_legend_handles_labels()
            ax_예수금.legend(h_손익 + h_예수금, l_손익 + l_예수금, loc='lower left', fontsize=8)
            ax_메인축.text(0.68, 0.84, f'예수금 {ary_거래후예수금[-1]:,.0f}', fontsize=9, fontweight='bold',
                        color=self.dic_색상['파랑'], va='top', ha='left', transform=ax_메인축.transAxes)

        return ax

    def ax_mfe산점도(self, ax, df_누적거래, n_손절선=None, n_목표선=None):
        """ 입력된 데이터 기준으로 MFE / MAE 그래프 생성 후 리턴
            n_손절선/n_목표선: 실제 매매 기준(%) 직접 지정 (미지정 시 손절/목표기준가를 매수가 대비 %로 환산) """
        # 데이터 정의 (매매 기준이 % 이므로 MFE/MAE 도 % 단위로 표기 - 손절/트레일 기준선과 직접 대조)
        ary_mfe = df_누적거래['mfe_수익률'].values
        ary_mae = df_누적거래['mae_수익률'].values
        ary_수익률 = df_누적거래['수익률'].values
        ary_수익여부 = ary_수익률 > 0

        # 그래프 설정 (기준선 = 지정값 우선, 없으면 손절/목표기준가를 매수가 대비 % 로 환산)
        n_목표라인 = round(n_목표선 if n_목표선 is not None else ((df_누적거래['목표기준가'] / df_누적거래['매수가'] - 1) * 100).max(), 1)
        n_손절라인 = round(n_손절선 if n_손절선 is not None else ((df_누적거래['손절기준가'] / df_누적거래['매수가'] - 1) * 100).max(), 1)
        ax.scatter(ary_mae[ary_수익여부], ary_mfe[ary_수익여부], s=55, c=self.dic_색상['빨강'],
                   alpha=.85, label=f'승 ({ary_수익여부.sum()})', edgecolors='white', linewidths=.6)
        ax.scatter(ary_mae[~ary_수익여부], ary_mfe[~ary_수익여부], s=45, c=self.dic_색상['파랑'],
                   alpha=0.7, label=f'패 ({(~ary_수익여부).sum()})', edgecolors='none')
        ax.axhline(n_목표라인, color=self.dic_색상['빨강'], ls='--', lw=1, alpha=.6, label=f'목표 +{n_목표라인}%')
        ax.axvline(n_손절라인, color=self.dic_색상['파랑'], ls='--', lw=1, alpha=.6, label=f'손절 {n_손절라인}%')

        # 스케일 설정
        ax.autoscale(enable=True, axis='both', tight=False)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6, integer=False))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, integer=False))
        ax.margins(x=0.05, y=0.05)

        # 뷰 설정
        ax.set_title('[ MFE vs MAE 산점도 ]', loc='left', fontsize=10, fontweight='bold')
        ax.set_ylabel('MFE (최대 유리 움직임, %)', fontsize=8)
        ax.set_xlabel('MAE (먼저 빠진 깊이, %)', fontsize=8)
        ax.grid(True, axis='y', color='gray', linestyle='--', linewidth=0.5, alpha=0.5)
        ax.legend(loc='upper left', fontsize=8)
        ax.tick_params(length=0, labelsize=8)
        ax.axhline(0, lw=0.5, alpha=1, color='black')
        ax.axvline(0, lw=0.5, alpha=1, color='black')

        return ax

    def ax_거래별mfe(self, ax, df_누적거래, n_손절선=None, n_목표선=None):
        """ 입력된 데이터 기준으로 MFE / MAE 그래프 생성 후 리턴
            n_손절선/n_목표선: 실제 매매 기준(%) 직접 지정 (미지정 시 손절/목표기준가를 매수가 대비 %로 환산) """
        # 데이터 정의
        df_누적거래 = df_누적거래.sort_values(['일자', '매수시점']).reset_index(drop=True)
        ary_x = df_누적거래.index
        ary_mfe = df_누적거래['mfe_수익률'].values
        ary_mae = df_누적거래['mae_수익률'].values

        # 그래프 설정 (기준선 = 지정값 우선, 없으면 손절/목표기준가를 매수가 대비 % 로 환산)
        n_목표라인 = round(n_목표선 if n_목표선 is not None else ((df_누적거래['목표기준가'] / df_누적거래['매수가'] - 1) * 100).max(), 1)
        n_손절라인 = round(n_손절선 if n_손절선 is not None else ((df_누적거래['손절기준가'] / df_누적거래['매수가'] - 1) * 100).max(), 1)
        ax.bar(ary_x, ary_mfe, color=self.dic_색상['빨강'], alpha=0.8, label='MFE')
        ax.bar(ary_x, ary_mae, color=self.dic_색상['파랑'], alpha=0.8, label='MAE')
        ax.axhline(n_목표라인, color=self.dic_색상['빨강'], ls='--', lw=0.8, alpha=0.5, label=f'목표 +{n_목표라인}%')
        ax.axhline(n_손절라인, color=self.dic_색상['파랑'], ls='--', lw=0.8, alpha=0.5, label=f'손절 {n_손절라인}%')

        # 스케일 설정
        ax.autoscale(enable=True, axis='both', tight=False)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6, integer=False))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, integer=False))
        ax.margins(x=0.05, y=0.05)

        # 뷰 설정
        ax.set_title('[ 거래별 MFE(위) / MAE(아래) ]', loc='left', fontsize=10, fontweight='bold')
        ax.set_xlabel('거래 순번', fontsize=8)
        ax.set_ylabel('%', fontsize=8)
        ax.grid(True, axis='y', color='gray', linestyle='--', linewidth=0.5, alpha=0.5)
        ax.legend(loc='upper left', fontsize=8)
        ax.tick_params(length=0, labelsize=8)
        ax.axhline(0, lw=0.5, alpha=1, color='black')

        return ax

    def ax_일봉거래(self, ax, dic_거래정보):
        """ 일봉 기준으로 거래정보 표기 후 리턴 """
        # 데이터 정의
        s_종목코드, s_종목명 = dic_거래정보.get('종목코드'), dic_거래정보.get('종목명')
        n_매수가, n_매도가 = dic_거래정보.get('매수가'), dic_거래정보.get('매도가')
        n_수익률, s_매도사유 = dic_거래정보.get('수익률'), dic_거래정보.get('매도사유')
        n_전일일봉고가, s_등장시간 = dic_거래정보.get('전일일봉고가'), '09:00:00'
        s_매도사유 = ('트레일' if s_매도사유 == '트레일청산' else
                   s_매도사유[:2] if s_매도사유 not in ['타임아웃', '보유초과'] else s_매도사유)
        s_거래일자 = f'{dic_거래정보.get('일자')[4:6]}-{dic_거래정보.get('일자')[6:8]}'
        df_일봉 = dic_거래정보.get('df_일봉', pd.DataFrame())

        # 차트 생성
        ax = self._make_캔들차트(ax=ax, df_차트=df_일봉, s_봉구분='일봉', s_차트구분='캔들')

        # 뷰 설정
        ax.set_title(f'[일봉] {s_종목명}({s_종목코드}) | {s_매도사유}({n_수익률:,.1f}%)',
                          loc='left', fontsize=10, fontweight='bold')
        ax.tick_params(length=0, labelsize=8)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5, integer=False))
        ax.axhline(n_전일일봉고가, color=self.dic_색상['빨강'], ls='--', lw=0.8, alpha=0.5, label=f'전일일봉고가 {n_전일일봉고가}')

        # 거래정보 설정
        ax.axvline(s_거래일자, lw=5, alpha=0.1, color=self.dic_색상['분홍'])
        ax.axhline(n_매수가, lw=2, alpha=0.4, color=self.dic_색상['분홍'])
        ax.axhline(n_매도가, lw=2, alpha=0.4, color=self.dic_색상['하늘'])

        return ax

    def ax_3분봉거래(self, ax, dic_거래정보):
        """ 일봉 기준으로 거래정보 표기 후 리턴 """
        # 데이터 정의
        s_종목코드, s_종목명 = dic_거래정보.get('종목코드'), dic_거래정보.get('종목명')
        n_매수가, n_매도가 = dic_거래정보.get('매수가'), dic_거래정보.get('매도가')
        n_수익률, s_매도사유 = dic_거래정보.get('수익률'), dic_거래정보.get('매도사유')
        n_전일일봉고가, s_등장시간 = dic_거래정보.get('전일일봉고가'), '09:00:00'
        s_매도사유 = ('트레일' if s_매도사유 == '트레일청산' else
                   s_매도사유[:2] if s_매도사유 not in ['타임아웃', '보유초과'] else s_매도사유)
        s_거래일자 = f'{dic_거래정보.get('일자')[4:6]}-{dic_거래정보.get('일자')[6:8]}'
        s_매수시점 = dic_거래정보.get('매수시점')
        s_매도시점 = dic_거래정보.get('매도시점')
        s_매수시점_분봉 = pd.Timestamp(s_매수시점).floor(f'3min').strftime('%H:%M')
        s_매도시점_분봉 = pd.Timestamp(s_매도시점).floor(f'3min').strftime('%H:%M')
        s_등장시간_분봉 = pd.Timestamp(s_등장시간).floor(f'3min').strftime('%H:%M') if s_등장시간 > '09:00:00' else '09:00'
        df_3분봉 = dic_거래정보.get('df_3분봉', pd.DataFrame())
        df_3분봉 = self._reindex_분봉(df_3분봉)   # 결측 시간대를 빈 봉으로 채워 연속 시간축 유지

        # 차트 생성
        ax = self._make_캔들차트(ax=ax, df_차트=df_3분봉, s_봉구분='분봉', s_차트구분='캔들')

        # 뷰 설정
        n_매수금액, n_손익금 = dic_거래정보.get('매수금액'), dic_거래정보.get('손익금')
        s_타이틀 = f'[3분봉] {s_종목명}({s_종목코드}) | {s_매도사유}({n_수익률:,.1f}%)'
        if n_매수금액 is not None and n_손익금 is not None:   # 예수금 사이징 전략에서만 금액 표기
            s_타이틀 += f' | 매수 {int(n_매수금액):,}원 / 손익 {int(n_손익금):+,}원'
        ax.set_title(s_타이틀, loc='left', fontsize=10, fontweight='bold')
        ax.tick_params(length=0, labelsize=8)
        # ax.xaxis.set_major_locator(MaxNLocator(nbins=5, integer=False))
        # ax.set_xticks([s_매수시점_분봉, s_매도시점_분봉], labels=[s_매수시점, s_매도시점])
        # ax.axvline('10:00', color=self.dic_색상['회색'], ls='--', lw=0.5, alpha=0.5)
        ax.set_xticks(['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00'])
        ax.axhline(n_전일일봉고가, color=self.dic_색상['빨강'], ls='--', lw=0.8, alpha=0.5, label=f'전일일봉고가 {n_전일일봉고가}')
        # ax.axvspan('09:00', s_등장시간_분봉, alpha=0.3, color=self.dic_색상['회색'], label=s_등장시간)

        # 거래정보 설정
        ax.axvline(s_매수시점_분봉, lw=2, alpha=0.3, color=self.dic_색상['분홍'], label=s_매수시점)
        ax.axvline(s_매도시점_분봉, lw=2, alpha=0.3, color=self.dic_색상['하늘'], label=s_매도시점)
        ax.axhline(n_매수가, lw=2, alpha=0.4, color=self.dic_색상['분홍'])
        ax.axhline(n_매도가, lw=2, alpha=0.4, color=self.dic_색상['하늘'])
        ax.legend(loc='upper right', fontsize=8)

        return ax

    @staticmethod
    def _reindex_분봉(df_분봉, s_시작='09:00:00', s_종료='15:30:00', s_주기='3min'):
        """ 3분봉을 장 시간(09:00~15:30) 연속 격자로 reindex - 결측 시간대를 빈 봉(NaN)으로 채움.
            중간 데이터 공백을 붕괴시키지 않고 빈칸으로 표시 + 정시 눈금 정렬(격자 1시간 간격) 용도 """
        if df_분봉 is None or len(df_분봉) == 0 or '시간' not in df_분봉.columns:
            return df_분봉
        ary_격자 = pd.date_range(f'2000-01-01 {s_시작}', f'2000-01-01 {s_종료}',
                               freq=s_주기).strftime('%H:%M:00')
        df = df_분봉.drop_duplicates('시간').set_index('시간').reindex(ary_격자)
        # 종목 식별 컬럼은 상수라 채워줌 (OHLCV·이평은 결측 유지 → 빈 봉)
        for s_컬럼 in ['일자', '종목코드', '종목명']:
            if s_컬럼 in df.columns:
                df[s_컬럼] = df_분봉[s_컬럼].iloc[0]
        return df.reset_index(names='시간')

    def _make_캔들차트(self, ax, df_차트, s_봉구분, s_차트구분, b_legend=True):
        """ df로 입력받은 일봉 데이터로 차트 생성하여 리턴 """
        # 기준정보 정의
        df_차트 = df_차트.sort_values('일자') if '일봉' in s_봉구분 else\
                df_차트.sort_values(['일자', '시간']) if '분봉' in s_봉구분 else\
                df_차트.reset_index(drop=True).sort_values(['체결시간']) if '초봉' in s_봉구분 else None

        # 그래프용 데이터 정의
        li_일시 = [f'{일자[4:6]}-{일자[6:8]}' for 일자 in df_차트['일자']] if '일봉' in s_봉구분 else\
                [시간[:5] for 시간 in df_차트['시간']] if '분봉' in s_봉구분 else\
                [시간 for 시간 in df_차트['체결시간']] if '초봉' in s_봉구분 else None
        ary_시가 = df_차트['시가'].values
        ary_고가 = df_차트['고가'].values
        ary_저가 = df_차트['저가'].values
        ary_종가 = df_차트['종가'].values
        ary_거래량 = df_차트['거래량'].values
        ary_바디 = (df_차트['종가'] - df_차트['시가']).replace(0, 0.5).values
        li_색상_캔들 = [self.dic_색상['파랑'] if 바디 < 0 else self.dic_색상['빨강'] for 바디 in ary_바디]
        li_색상_거래량 = [self.dic_색상['파랑'] if 거래량차이 < 0 else self.dic_색상['빨강']
                     for 거래량차이 in (df_차트['거래량'] - df_차트['거래량'].shift(1))]
        ary_종가ma5 = df_차트['종가ma5'].values
        ary_종가ma10 = df_차트['종가ma10'].values
        ary_종가ma20 = df_차트['종가ma20'].values
        ary_종가ma60 = df_차트['종가ma60'].values
        ary_종가ma120 = df_차트['종가ma120'].values
        ary_거래량ma5 = df_차트['거래량ma5'].values
        ary_거래량ma20 = df_차트['거래량ma20'].values
        ary_거래량ma60 = df_차트['거래량ma60'].values
        ary_거래량ma120 = df_차트['거래량ma120'].values

        # 그래프 설정
        if s_차트구분 == '캔들':
            ax.bar(li_일시, height=ary_바디, bottom=ary_시가, width=0.8, color=li_색상_캔들)
            ax.vlines(li_일시, ary_저가, ary_고가, lw=0.5, color=li_색상_캔들)
            ax.plot(li_일시, ary_종가ma5, lw=0.5, color=self.dic_색상['분홍'], label='ma5')
            ax.plot(li_일시, ary_종가ma10, lw=0.5, color=self.dic_색상['파랑'], label='ma10')
            ax.plot(li_일시, ary_종가ma20, lw=2, color=self.dic_색상['주황'], label='ma20', alpha=0.5)
            ax.plot(li_일시, ary_종가ma60, lw=0.5, color=self.dic_색상['녹색'], label='ma60')
            ax.plot(li_일시, ary_종가ma120, lw=2, color='black', label='ma120', alpha=0.5)

            # 스케일 설정
            li_대상컬럼 = ['저가', '고가', '종가ma5', '종가ma10', '종가ma20', '종가ma60', '종가ma120']
            n_최소값 = df_차트.loc[:, li_대상컬럼].min().min()
            n_최대값 = df_차트.loc[:, li_대상컬럼].max().max()
            ax.set_ylim(n_최소값 * 0.98, n_최대값 * 1.02)

        if s_차트구분 == '거래량':
            ax.bar(li_일시, ary_거래량, width=0.8, color=li_색상_거래량)
            ax.plot(li_일시, ary_거래량ma5, lw=0.5, color=self.dic_색상['분홍'], label='ma5')
            ax.plot(li_일시, ary_거래량ma20, lw=2, color=self.dic_색상['주황'], label='ma20', alpha=0.5)
            ax.plot(li_일시, ary_거래량ma60, lw=0.5, color=self.dic_색상['녹색'], label='ma60')
            ax.plot(li_일시, ary_거래량ma120, lw=0.5, color='black', label='ma120')

        # 뷰 설정
        ax.grid(True, color='gray', linestyle='--', linewidth=0.5, alpha=0.5)
        ret = ax.legend(loc='upper left', fontsize=8) if b_legend else None

        return ax


if __name__ == "__main__":
    c = ChartMaker()
    pass
