import os
import re
import sys
import json
import time
from collections import deque

import pandas as pd
import multiprocessing as mp
import asyncio

import ut, xapi

# 매수세 전략 파라미터 (bot_백테스팅_틱기반매수세와 동일 - 환경변수로 동기 조정)
# 진입
_T_순매수비율 = float(os.environ.get('TB_RATIO', '0.6'))      # 60초 순매수비율 임계값 (매수세 형성) - 0.4→0.6: 진입의 절반이 기대값 0(제외군 평균 -0.03%)이라 노이즈 제거용.
#                                                              플래토 0.55~0.65. 총수익 증가가 아니라 변동성 감소가 목적(교차검증상 총수익은 본전, 적자일 제거)
_T_거래강도 = float(os.environ.get('TB_INT', '5.0'))          # 직전 5분 대비 60초 거래량 배수 (상대 서지)
_T_최소거래량 = int(os.environ.get('TB_MINVOL60', '10000'))    # 60초 절대 거래량 바닥 (주) - 얇은종목 '살짝 흔들림' 배제
_T_단주 = int(os.environ.get('TB_MINQTY', '2'))              # 단주 필터: |틱거래량| <= 값이면 매수세 계산서 제외 (흐름조작 배제)
_T_이격최소 = float(os.environ.get('TB_DIST', '5.0'))         # 당일고가 대비 최소 이격 % (눌림 필터)
_T_이격최대 = float(os.environ.get('TB_DISTMAX', '14'))       # 당일고가 대비 최대 이격 % 상한 (낙폭과대=칼날 배제) - 전수스캔상 이격 14~16부터 승률 10%로 급락
_T_체결속도 = float(os.environ.get('TB_SPEED', '3.5'))        # 직전 5분 대비 60초 유효틱 건수 배수 (체결속도 서지) - 큰상승은 중간크기 매수가 빠르게 연속
_T_덩어리상한 = float(os.environ.get('TB_CHUNKMAX', '30'))     # 60초 내 최대 매수틱 ÷ 평균틱크기 상한 - 단일 대형블록 주도(미끼성)는 흐지부지 -> 배제
_T_일최대거래 = int(os.environ.get('TB_MAXPERDAY', '2'))       # 종목당 1일 최대 진입 횟수
_T_쿨다운 = int(os.environ.get('TB_COOLDOWN', '300'))         # 청산 후 재진입 대기 (초) - 트레일링 청산 전환 후 단축 (수익청산 직후 재점화 포착)
# 청산 (신호소멸 청산 제거 - 매수세 신호는 ~10분에 소멸하나 가격 추세는 더 감 → 청산은 가격 트레일링이 담당)
_T_손절 = float(os.environ.get('TB_STOP', '1.5'))            # 손절 % (매수가 대비) - 2.0→1.5: 약세일 손실 축소 (전수스캔 기반 재설계)
_T_트레일 = float(os.environ.get('TB_TRAIL', '2.5'))          # 트레일링 스탑 % (보유중 고점 대비) - 3.0→2.5: 약세일 승자 피크가 +3% 언저리라 3%는 이익 전부 반납, 2.5 이하라야 비용 제하고 양수 마감
_T_본전발동 = float(os.environ.get('TB_BEARM', '1.5'))        # 본전방어 발동 % (보유중 고점이 매수가 대비 이 이상 도달하면 스탑 하한을 본전+비용으로 상향, 0=미사용)
#                                                              트레일 2.5%의 손익분기 피크는 +2.92% - 그 미만 피크는 트레일 청산이 반드시 마이너스라 하한으로 방어
_T_최대보유 = int(os.environ.get('TB_MAXHOLD', '3600'))       # 최대 보유시간 (초) - 스탑 미터치 횡보 시 강제 타임아웃 매도
_T_비용 = float(os.environ.get('TB_COST', '0.35'))           # 왕복 거래비용 % (본전방어 하한 산출용, 백테스팅과 동일)
# ─── 구간1 (개장 09:00~09:10) : 흐름추종 진입 + 트레일 청산 (백테스팅과 동일 정의) ────────────
# 위 로직(구간2=눌림매매)은 개장초에 구조적으로 진입 불가 - 당일고가 미형성으로 이격률 평균 2.8%(<요구 5%),
# 상대지표(거래강도·체결속도)도 개장초엔 기준선 자체가 높아 서지 미검출. 6일 전수재생상 09:00~09:30 신호 0건.
# 반면 개장초 기회 밀도는 2~3배 → 절대기준 흐름추종으로 분리 대응 (2026-07-27)
_G1_사용 = os.environ.get('TB_G1', '1') == '1'               # 구간1 로직 사용 여부 (0=기존 동작)
_G1_종료 = int(os.environ.get('TB_G1END', '600'))            # 구간1 종료 (09:00 기준 초, 600=09:10)
_G1_체결률 = float(os.environ.get('TB_G1RATE', '7.0'))        # 유효 매수 체결 횟수 하한 (초당, 10초창, 절대기준)
_G1_순매수 = float(os.environ.get('TB_G1RATIO', '0.5'))       # 순매수비율 하한 (체결률과 동일한 10초창)
_G1_창 = int(os.environ.get('TB_G1WIN', '10'))               # 체결률·순매수 산출 창 (초)
_G1_상승창 = int(os.environ.get('TB_G1UP', '10'))             # 단가 상승 판정 (N초 전 대비)
_G1_트레일 = float(os.environ.get('TB_G1TRAIL', '2.0'))       # 트레일링 스탑 % - 매수세 소멸 청산보다 우수함이 검증됨
_G1_손절 = float(os.environ.get('TB_G1STOP', '1.5'))         # 손절 %
_G1_최대보유 = int(os.environ.get('TB_G1HOLD', '1800'))       # 최대 보유 (초)
_G1_쿨다운 = int(os.environ.get('TB_G1COOL', '180'))          # 청산 후 재진입 대기 (초)
_G1_일최대 = int(os.environ.get('TB_G1MAX', '2'))             # 종목당 구간1 최대 진입 횟수
_G1_분할수 = int(os.environ.get('TB_G1DIVISOR', '4'))          # 구간1 전용 분할 수 (구간2는 _T_분할수=3)
#                                                              구간1은 09:00~09:10에 신호가 몰리고 평균보유 347초라 서로 겹침.
#                                                              자본무관 최대 동시보유가 4종목인데 3분할이면 4번째가 잔돈으로만 체결됨
#                                                              (실측: 07/20 기가레인 목표 337만→실제 4.9만(1%), 07/23 한울반도체 404만→11.8만(3%) - 둘 다 큰 승자)
_G1_매수호가 = int(os.environ.get('TB_G1TICKUP', '5'))         # 구간1 매수 지정가 = 현재가 + N호가 (구간2는 _T_매수호가=3)
#                                                              구간1은 체결 폭증 한복판 진입이라 호가가 빠르게 밀림 → 더 공격적으로 잡아 미체결 방지
# 종목선정 (전일 일봉 기준)
_T_최소거래대금 = float(os.environ.get('TB_MINVALUE', '5000'))  # 전일 거래대금 하한 (백만원)
_T_최소가격 = float(os.environ.get('TB_MINPRICE', '1000'))     # 전일 종가 하한 (원)
# 실매매 전용 (총자산 균등 사이징 + 리스크 한계)
_T_분할수 = int(os.environ.get('TB_DIVISOR', '3'))            # 총자산 균등 분할 수 (진입당 매수금액 = 총자산 / 분할수) - 5→3: 백테 5일 최대 동시보유 3종목이라 5칸 미사용·자본 80% 유휴, 3분할이 신호 전량 체결하며 자본효율 최대(계좌수익 +8.4→+14.3%, 최악일 -0.62%)
_T_리스크캡 = float(os.environ.get('TB_RISKCAP', '1.0'))      # 거래당 리스크 한계 (총자본 %) - 손절 깊을 때만 실효(임계=분할수×리스크캡%)
_T_주문금액 = int(os.environ.get('TB_ORDERAMT', '500000'))     # 예수금/잔고 조회 실패 시 폴백 주문금액 (원)
_T_최대보유종목 = int(os.environ.get('TB_MAXPOS', '999'))      # 동시 보유 최대 종목 수 (기본 무제한 - 백테스팅 동일, 자본 제약 시 축소)
_T_주문타임아웃 = int(os.environ.get('TB_ORDTIMEOUT', '90'))   # 주문 후 체결 확인 대기 (초)
_T_매도재시도간격 = int(os.environ.get('TB_SELLGAP', '15'))    # 매도 재시도 최소 간격 (초) - 실패 시 매 완결초 재호출 폭주(429) 방지
# 디버그 (진입조건 추적 - 백테스팅과 실시간 신호 불일치 조사용, 미지정 시 완전 무영향)
_T_디버그종목 = {c.strip() for c in os.environ.get('TB_DEBUG', '').split(',') if c.strip()}   # 추적할 종목코드 (콤마구분)
_T_디버그간격 = int(os.environ.get('TB_DEBUGGAP', '60'))       # 디버그 스냅샷 최소 간격 (초) - 코어신호 충족 시엔 항상 로깅
_T_매수호가 = int(os.environ.get('TB_TICKUP', '3'))           # 매수 지정가 = 현재가 + N호가 (즉시체결 확률 확보, 증거금은 지정가 기준)


# noinspection NonAsciiCharacters,SpellCheckingInspection,PyPep8Naming,PyTypeChecker,PyAttributeOutsideInit,PyUnresolvedReferences
class TraderBot:
    """ 틱 기반 매수세 실시간 매매 (백테스팅 bot_백테스팅_틱기반매수세와 동일 로직)
        - 진입: 매수세 형성 (60초 순매수비율/거래강도/체결속도) + 눌림(당일고가 대비 이격) + 덩어리배수 상한 필터
        - 청산: 트레일링 스탑 (보유중 고점 대비 %) / 손절 / 장마감 """

    def __init__(self, queue_mp_수신2매매=None):
        # config 읽어 오기
        self.folder_베이스 = os.path.dirname(os.path.abspath(__file__))
        self.folder_프로젝트 = os.path.dirname(self.folder_베이스)
        self.s_파일명 = os.path.basename(__file__).replace('.py', '')
        dic_config = ut.도구manager.ToolManager().config로딩()

        # 로그 설정
        log = ut.로그maker.LogMaker(s_파일명=self.s_파일명, s_로그명='로그이름_trader')
        sys.stderr = ut.로그maker.StderrHook(path_에러로그=log.path_에러)
        self.make_로그 = log.make_로그

        # 폴더 정의
        dic_폴더정보 = ut.폴더manager.FolderManager().dic_폴더정보
        self.folder_감시종목 = dic_폴더정보['매수매도|감시종목']
        self.folder_잔고 = dic_폴더정보['매수매도|종목잔고']
        os.makedirs(self.folder_잔고, exist_ok=True)
        self.folder_서버 = ('/Volumes/extSSD4tb/80_Backup/10_python_backup/ProjectWork/spTraderV2'
                          if sys.platform == 'darwin' else '')

        # api 정의 (주문용 - 웹소켓 데이터는 수신 모듈이 큐로 전달)
        self.restapi = xapi.RestAPI_kiwoom.RestAPIkiwoom()

        # queue 생성
        self.queue_mp_수신2매매 = queue_mp_수신2매매

        # 기준정보 정의
        self.s_오늘 = pd.Timestamp.now().strftime('%Y%m%d')
        self.fid_체결 = xapi.wsFID_kiwoom.fid_주식체결_0B()
        self.fid_주문 = xapi.wsFID_kiwoom.fid_주문체결_00()
        self.n_장마감초 = 15 * 3600 + 15 * 60    # 15:15 이후 신규진입 금지 + 보유분 청산
        self.tool = ut.도구manager.ToolManager()

        # 종목별 상태 정의
        self.set_매매대상 = set()      # 종목선정 통과 종목
        self.dic_종목명 = dict()
        self.dic_지표 = dict()         # 종목코드: dict(버킷=deque[(초,매수,매도)], 첫초, 직전고가)
        self.dic_포지션 = dict()       # 종목코드: dict(상태, 수량, 매수가, 매수초, 진입횟수, 청산초, 주문초, 매도재시도)
        self.path_포지션 = os.path.join(self.folder_잔고, f'dic_포지션_{self.s_오늘}.pkl')    # 재시작 복원용

        # 로그 기록
        self.make_로그(f'구동 시작 - 사이징(총자산÷{_T_분할수} 균등, 리스크캡 총자본 {_T_리스크캡:.1f}%/손절 {_T_손절:.1f}%), '
                     f'최대보유 {_T_최대보유종목}종목')

    # -----------------------------------------------------------------
    async def set_매매대상선정(self):
        """ 감시종목 중 전일 일봉 기준 매매 대상 선정 (백테스팅 pick_종목선정과 동일 필터) """
        # 감시종목 불러오기 - '당일 파일'을 기다린다 (수신 모듈 make_감시종목이 1~2초 뒤 생성)
        # 과거 파일 존재만으로 통과시키면 전일 목록으로 하루를 감시하게 됨 (2026-07-23 실장애: 전일 대비 6종목 상이,
        # 그중 유일한 신호 종목이 당일 신규분이라 미진입. 양일 모두 41개라 건수 로그로는 식별 불가했음)
        s_파일 = None
        for _ in range(60):
            li_당일 = [파일 for 파일 in os.listdir(self.folder_감시종목)
                     if '.pkl' in 파일 and re.findall(r'\d{8}', 파일)[0] == self.s_오늘]
            if len(li_당일) > 0:
                s_파일 = max(li_당일)
                break
            await asyncio.sleep(1)
        if s_파일 is None:      # 당일 파일 미생성 - 최신 과거 파일로 폴백 (감시 중단보다는 낫되 반드시 경고)
            li_과거 = [파일 for 파일 in os.listdir(self.folder_감시종목)
                     if '.pkl' in 파일 and re.findall(r'\d{8}', 파일)[0] < self.s_오늘]
            if len(li_과거) == 0:
                self.make_로그('!!! 감시종목 파일 미존재 - 매매대상 선정 중단 (매매 불가)')
                return
            s_파일 = max(li_과거)
            self.make_로그(f'!!! 당일 감시종목 파일 미생성 (60초 대기 초과) - 과거 파일로 폴백: {s_파일}')
        dic_감시종목 = pd.read_pickle(os.path.join(self.folder_감시종목, s_파일))
        li_감시종목 = dic_감시종목.get('매매대상', list()) + dic_감시종목.get('수집대상', list())

        # 전일 일봉 필터 (거래대금/가격)
        folder_일봉 = os.path.join(self.folder_서버, '데이터', '차트캐시', '일봉1')
        li_일봉파일 = sorted(파일 for 파일 in os.listdir(folder_일봉)
                        if '.pkl' in 파일 and re.findall(r'\d{8}', 파일)[0] < self.s_오늘)
        dic_일봉 = pd.read_pickle(os.path.join(folder_일봉, li_일봉파일[-1])) if len(li_일봉파일) > 0 else dict()
        for s_종목코드 in li_감시종목:
            df_일봉 = dic_일봉.get(s_종목코드, None)
            if df_일봉 is None or len(df_일봉) == 0:
                continue
            sri_전일 = df_일봉.iloc[-1]
            if (sri_전일['거래대금(백만)'] >= _T_최소거래대금) and (sri_전일['종가'] >= _T_최소가격):
                self.set_매매대상.add(s_종목코드)
                self.dic_종목명[s_종목코드] = sri_전일['종목명']

        # 로그 기록 - 사용한 감시종목 파일 + 선정 종목코드 명시 (건수만으로는 전일 목록 오사용을 식별 못함)
        li_매매대상 = [코드 for 코드 in li_감시종목 if 코드 in self.set_매매대상]   # 감시종목 순서 유지
        self.make_로그(f'{s_파일} 기준 - 감시 {len(li_감시종목)}개 중 매매대상 {len(li_매매대상)}개 선정\n'
                     f' - {li_매매대상}')

    # -----------------------------------------------------------------
    def _lbl(self, s_종목코드):
        """ 로그용 종목 라벨 - 종목코드는 항상 종목명과 함께 표기 """
        return f'{self.dic_종목명.get(s_종목코드, s_종목코드)}({s_종목코드})'

    @staticmethod
    def _초2시(n_초):
        """ 초 → HH:MM:SS (디버그 로그용) """
        n = int(n_초)
        return f'{n // 3600:02d}:{n % 3600 // 60:02d}:{n % 60:02d}'

    @staticmethod
    def _호가단위(n_가격):
        """ KRX 호가가격단위 (2023-01-25~ 코스피·코스닥 통합) """
        if n_가격 < 2000:
            return 1
        if n_가격 < 5000:
            return 5
        if n_가격 < 20000:
            return 10
        if n_가격 < 50000:
            return 50
        if n_가격 < 200000:
            return 100
        if n_가격 < 500000:
            return 500
        return 1000

    def _매수단가(self, n_현재가, n_호가수=None):
        """ 매수 지정가 = 현재가 + N호가 (호가 경계마다 단위 재계산하며 한 틱씩 상승) """
        n_단가 = int(n_현재가)
        for _ in range(_T_매수호가 if n_호가수 is None else n_호가수):
            n_단가 += self._호가단위(n_단가)
        return n_단가

    # -----------------------------------------------------------------
    def _save_포지션(self):
        """ 포지션 상태를 당일 파일로 저장 (재시작 복원용) """
        try:
            pd.to_pickle(self.dic_포지션, self.path_포지션)
        except Exception as e:
            print(f'포지션 저장 실패 - {e}', file=sys.stderr)

    # -----------------------------------------------------------------
    def restore_포지션(self):
        """ 봇 재시작 시 포지션 복원 - 당일 포지션 파일과 계좌잔고 대조
            (파일에 기록된 전략 포지션만 복원, 잔고에만 있는 수동 보유는 건드리지 않음) """
        # 당일 포지션 파일 확인 (없으면 정상 기동 - 복원 불필요)
        if not os.path.exists(self.path_포지션):
            return
        try:
            dic_포지션_파일 = pd.read_pickle(self.path_포지션)
        except Exception as e:
            self.make_로그(f'포지션 파일 로딩 실패 - 복원 생략 - {e}')
            return
        if len(dic_포지션_파일) == 0:
            return

        # 계좌잔고 조회 (실제 보유 확인)
        try:
            dic_계좌잔고, df_종목별잔고 = self.restapi.tr_체결잔고요청()
            dic_잔고 = (df_종목별잔고.set_index('종목코드')['현재잔고'].to_dict()
                      if len(df_종목별잔고) > 0 else dict())
        except Exception as e:
            self.make_로그(f'잔고조회 실패 - 포지션 복원 생략 (수동 확인 필요) - {e}')
            return

        # 파일 기록과 잔고 대조 후 복원
        li_복원, li_정리 = list(), list()
        for s_종목코드, dic_기록 in dic_포지션_파일.items():
            n_잔고수량 = int(dic_잔고.get(s_종목코드, 0))
            b_보유기록 = dic_기록.get('상태') in ['매수중', '보유', '매도중'] and dic_기록.get('수량', 0) >= 0

            # 기록상 보유(진행) + 실제 잔고 있음 -> 보유 복원 (수량은 실제 잔고 기준)
            if b_보유기록 and n_잔고수량 > 0:
                dic_기록.update(상태='보유', 수량=n_잔고수량, 매도재시도=0)
                self.dic_포지션[s_종목코드] = dic_기록
                self.set_매매대상.add(s_종목코드)    # 청산 감시를 위해 대상 유지
                li_복원.append(f'{self._lbl(s_종목코드)} {n_잔고수량}주')

            # 기록상 보유였으나 잔고 없음 -> 이미 청산됨 (진입횟수/청산이력은 유지)
            else:
                dic_기록.update(상태='없음', 수량=0)
                self.dic_포지션[s_종목코드] = dic_기록
                li_정리.append(self._lbl(s_종목코드))

        # 잔고에만 있는 종목 - 전략 기록 없음 -> 수동 보유로 간주, 미개입 (로그만)
        li_수동보유 = [self._lbl(코드) for 코드, 수량 in dic_잔고.items()
                   if 수량 > 0 and 코드 not in dic_포지션_파일]

        # 로그 기록
        self.make_로그(f'포지션 복원 - 보유 {len(li_복원)}건 {li_복원}\n'
                     f' - 청산확인 {len(li_정리)}건, 수동보유(미개입) {len(li_수동보유)}건 {li_수동보유}')
        self._save_포지션()

    # -----------------------------------------------------------------
    async def exec_종목감시(self):
        """ 큐에서 들어오는 체결/주문 데이터 대상으로 매매조건 감시 및 주문 """
        # 루프 구동
        while True:
            # 데이터 수신
            try:
                dic_데이터 = self.queue_mp_수신2매매.get_nowait()
                s_데이터타입 = dic_데이터['name']
                s_종목코드 = dic_데이터['item']
                dic_데이터_변동 = dic_데이터['values']
            except mp.queues.Empty:
                await asyncio.sleep(0.01)
                continue
            except (TypeError, KeyError):
                continue

            # 데이터 타입별 처리
            try:
                if s_데이터타입 == '주식체결':
                    self._proc_체결틱(s_종목코드=s_종목코드, dic_값=dic_데이터_변동)
                elif s_데이터타입 == '주문체결':
                    self._proc_주문체결(s_종목코드=s_종목코드, dic_값=dic_데이터_변동)
            except Exception as e:
                print(f'매매처리 오류 - {self._lbl(s_종목코드)} - {e}', file=sys.stderr)

    # -----------------------------------------------------------------
    def _proc_체결틱(self, s_종목코드, dic_값):
        """ 주식체결 틱 처리 - 지표 업데이트 후 진입/청산 판단 (백테스팅과 동일 지표) """
        # 매매대상 외 종목 제외
        if s_종목코드 not in self.set_매매대상:
            return

        # 틱 데이터 파싱
        fid = self.fid_체결.dic_이름2코드
        try:
            s_시간 = str(dic_값[fid['체결시간']]).strip()
            n_초 = int(s_시간[:2]) * 3600 + int(s_시간[2:4]) * 60 + int(s_시간[4:6])
            n_현재가 = abs(int(dic_값[fid['현재가']]))
            n_거래량 = int(dic_값[fid['거래량']])            # 부호: +매수 / -매도
            n_당일고가 = abs(int(dic_값[fid['고가']]))
        except (KeyError, ValueError, IndexError):
            return

        # 지표 상태 초기화
        if s_종목코드 in _T_디버그종목 and s_종목코드 not in self.dic_지표:   # 디버그: 첫 틱 수신시각 (워밍업 시작점)
            self.make_로그(f'[디버그] {self._lbl(s_종목코드)} 첫틱수신 {self._초2시(n_초)} (워밍업 종료 {self._초2시(n_초 + 360)})')
        dic_지표 = self.dic_지표.setdefault(
            s_종목코드, dict(버킷=deque(), 첫초=n_초, 직전고가=n_당일고가, 직전가=n_현재가, 판정초=0))

        # 주문 타임아웃 안전장치 (시장가 미체결 방지)
        dic_포지션 = self.dic_포지션.setdefault(
            s_종목코드, dict(상태='없음', 수량=0, 매수가=0, 매수초=0, 진입횟수=0, 청산초=0, 주문초=0, 매도재시도=0))
        if dic_포지션['상태'] == '매수중' and n_초 - dic_포지션['주문초'] > _T_주문타임아웃:
            self.make_로그(f'매수 체결확인 실패 - {self._lbl(s_종목코드)} - 상태 초기화')
            dic_포지션['상태'] = '없음'
            self._save_포지션()
        if dic_포지션['상태'] == '매도중' and n_초 - dic_포지션['주문초'] > _T_주문타임아웃:
            if dic_포지션['매도재시도'] < 3:
                dic_포지션['매도재시도'] += 1
                self.make_로그(f'매도 체결확인 실패 - {self._lbl(s_종목코드)} - 재시도 {dic_포지션["매도재시도"]}회')
                self._send_매도(s_종목코드=s_종목코드, dic_포지션=dic_포지션, n_초=n_초, s_사유='재시도')

        # 판정 실행 - 직전 틱 이후 경과한 모든 완결초를 순차 판정 (백테스팅의 매초 1초봉 판정과 동일 의미)
        # (거래 없는 초에도 윈도우 경계 이동으로 신호가 발생할 수 있음 - 체결은 현재 틱 가격)
        buk = dic_지표['버킷']
        if len(buk) > 0 and n_초 > buk[-1][0]:
            # 판정 시작: 구간1은 10초 창이면 성립하므로 웜업 360초를 기다리지 않는다.
            # (구간2 조건은 _judge_바 안에서 첫초+361 게이트로 기존과 동일하게 유지)
            # ※ 361을 그대로 두면 09:06 이전 진입이 원천 차단되어 구간1이 한 건도 체결되지 않음
            n_웜업오프셋 = _G1_상승창 if _G1_사용 else 361
            n_시작초 = max(dic_지표['판정초'] + 1, dic_지표['첫초'] + n_웜업오프셋)
            for n_완결초 in range(n_시작초, n_초):
                self._judge_바(s_종목코드=s_종목코드, dic_지표=dic_지표, n_완결초=n_완결초, n_주문참고가=n_현재가)
            dic_지표['판정초'] = n_초 - 1

        # 윈도우 버킷 업데이트 (초 단위 합산) - 단주(|거래량|<=_T_단주)는 매수세서 제외 (흐름조작 배제)
        # 버킷 = [초, 매수량, 매도량, 유효틱수, 최대매수틱, 매수틱수, 종가]
        #        (매수틱수·종가는 구간1용 - 초당 매수 체결 '횟수'와 단가상승 판정)
        n_매수량 = n_거래량 if n_거래량 > _T_단주 else 0
        n_매도량 = -n_거래량 if n_거래량 < -_T_단주 else 0
        n_유효틱 = 1 if (n_매수량 > 0 or n_매도량 > 0) else 0
        n_매수틱 = 1 if n_매수량 > 0 else 0
        if len(buk) > 0 and buk[-1][0] == n_초:
            buk[-1][1] += n_매수량
            buk[-1][2] += n_매도량
            buk[-1][3] += n_유효틱
            buk[-1][4] = max(buk[-1][4], n_매수량)
            buk[-1][5] += n_매수틱
            buk[-1][6] = n_현재가
        else:
            buk.append([n_초, n_매수량, n_매도량, n_유효틱, n_매수량, n_매수틱, n_현재가])
        while len(buk) > 0 and buk[0][0] < n_초 - 720:    # 보수적 유지 (판정 윈도우는 합산 시 명시적 경계 사용)
            buk.popleft()
        dic_지표['직전고가'] = n_당일고가    # 다음 판정용 (백테스팅 shift(1)과 동일)
        dic_지표['직전가'] = n_현재가

    # -----------------------------------------------------------------
    def _judge_바(self, s_종목코드, dic_지표, n_완결초, n_주문참고가):
        """ 완결초 하나에 대한 매매 판정 (백테스팅 1초봉 판정과 동일 정의) """
        # 매수세 지표 계산
        buk = dic_지표['버킷']
        li_60 = [b for b in buk if n_완결초 - 60 < b[0] <= n_완결초]
        li_300 = [b for b in buk if n_완결초 - 360 < b[0] <= n_완결초 - 60]    # 직전 300초 (60~360초 전)
        n_매수60 = sum(b[1] for b in li_60)
        n_매도60 = sum(b[2] for b in li_60)
        n_전체60 = n_매수60 + n_매도60
        n_전체300 = sum(b[1] + b[2] for b in li_300)
        n_순매수비율 = (n_매수60 - n_매도60) / n_전체60 if n_전체60 > 0 else 0
        n_거래강도 = n_전체60 / (n_전체300 / 5) if n_전체300 > 0 else 0
        # 신규 지표: 체결속도(건수 서지) + 덩어리배수(단일 대형블록 판별) - 백테스팅과 동일 정의
        n_틱수300 = sum(b[3] for b in li_300)
        n_체결속도 = sum(b[3] for b in li_60) / (n_틱수300 / 5) if n_틱수300 > 0 else 0
        n_평균틱 = n_전체300 / n_틱수300 if n_틱수300 > 0 else 0                # 직전 5분 평균 틱크기
        n_덩어리배수 = (max((b[4] for b in li_60), default=0) / n_평균틱 if n_평균틱 > 0 else 0)
        n_판정가 = dic_지표['직전가']          # 완결초까지의 마지막 체결가 (백테스팅 ffill과 동일)
        n_이격률 = ((dic_지표['직전고가'] - n_판정가) / dic_지표['직전고가'] * 100
                 if dic_지표['직전고가'] > 0 else 0)

        # 구간1 지표 (10초 창, 절대기준) - 백테스팅 G1체결률/G1순매수/G1상승과 동일 정의
        li_10 = [b for b in buk if n_완결초 - _G1_창 < b[0] <= n_완결초]
        n_G1체결률 = sum(b[5] for b in li_10) / _G1_창                        # 초당 매수 체결 횟수
        n_G1매수, n_G1매도 = sum(b[1] for b in li_10), sum(b[2] for b in li_10)
        n_G1순매수 = ((n_G1매수 - n_G1매도) / (n_G1매수 + n_G1매도)) if (n_G1매수 + n_G1매도) > 0 else 0
        li_과거 = [b for b in buk if b[0] <= n_완결초 - _G1_상승창]              # ffill: 해당 시각 이하 최신 체결가
        b_G1상승 = (n_판정가 > li_과거[-1][6]) if len(li_과거) > 0 else False

        # 포지션 상태 확인
        dic_포지션 = self.dic_포지션.setdefault(
            s_종목코드, dict(상태='없음', 수량=0, 매수가=0, 매수초=0, 진입횟수=0, 청산초=0, 주문초=0, 매도재시도=0))

        # 디버그: 진입조건 각 항목 추적 (TB_DEBUG 지정 종목만) - 코어신호 충족 시 항상 + 그 외 간격마다
        if s_종목코드 in _T_디버그종목:
            b_c1, b_c2 = n_순매수비율 > _T_순매수비율, n_거래강도 > _T_거래강도
            b_c3, b_c4 = n_전체60 >= _T_최소거래량, (_T_이격최소 <= n_이격률 < _T_이격최대)
            b_c5, b_c6 = n_체결속도 >= _T_체결속도, n_덩어리배수 <= _T_덩어리상한
            b_코어 = b_c1 and b_c2 and b_c3 and b_c4 and b_c5 and b_c6
            if b_코어 or (n_완결초 - dic_지표.get('디버그초', 0) >= _T_디버그간격):
                dic_지표['디버그초'] = n_완결초
                b_쿨 = n_완결초 >= dic_포지션['청산초'] + _T_쿨다운
                self.make_로그(f'[디버그] {self._lbl(s_종목코드)} {self._초2시(n_완결초)} '
                             f'비율{n_순매수비율:+.2f}{"O" if b_c1 else "X"} '
                             f'강도{n_거래강도:.1f}{"O" if b_c2 else "X"} '
                             f'전체60={n_전체60:,.0f}{"O" if b_c3 else "X"} '
                             f'이격{n_이격률:+.1f}{"O" if b_c4 else "X"} '
                             f'속도{n_체결속도:.1f}{"O" if b_c5 else "X"} '
                             f'덩어리{n_덩어리배수:.0f}{"O" if b_c6 else "X"} '
                             f'→ {"코어신호O" if b_코어 else "미충족"} '
                             f'[{dic_포지션["상태"]} 진입{dic_포지션["진입횟수"]}회 쿨다운{"OK" if b_쿨 else "대기"}]')

        # 청산 판단 (보유 시) - 스탑 판정은 완결초 가격 기준 (백테스팅과 동일)
        if dic_포지션['상태'] == '보유':
            n_경과 = n_완결초 - dic_포지션['매수초']
            b_G1포지션 = dic_포지션.get('구간') == '구간1'      # 진입 구간의 청산 규칙을 따른다
            # 보유중 고점 갱신 (트레일링 기준) - 매수가에서 시작, 완결초 판정가로 갱신 (백테스팅 누적고점과 동일)
            n_피크가 = max(dic_포지션.get('피크가', dic_포지션['매수가']), n_판정가)
            dic_포지션['피크가'] = n_피크가
            n_매수가 = dic_포지션['매수가']
            n_손절률 = _G1_손절 if b_G1포지션 else _T_손절
            n_트레일률 = _G1_트레일 if b_G1포지션 else _T_트레일
            n_최대보유 = _G1_최대보유 if b_G1포지션 else _T_최대보유
            n_손절가 = n_매수가 * (1 - n_손절률 / 100)
            n_스탑가 = max(n_손절가, n_피크가 * (1 - n_트레일률 / 100))
            # 본전방어: 고점이 매수가 대비 _T_본전발동% 도달 후엔 스탑 하한을 본전(+비용)으로 상향 (구간2 전용)
            if _T_본전발동 > 0 and not b_G1포지션 and n_피크가 >= n_매수가 * (1 + _T_본전발동 / 100):
                n_스탑가 = max(n_스탑가, n_매수가 * (1 + _T_비용 / 100))
            b_손절 = n_판정가 <= n_손절가
            b_트레일 = (not b_손절) and (n_판정가 <= n_스탑가)
            b_보유초과 = n_경과 >= n_최대보유      # 스탑 미터치 횡보 - 강제 타임아웃
            b_마감 = n_완결초 >= self.n_장마감초
            if b_손절 or b_트레일 or b_보유초과 or b_마감:
                # 매도 실패 시 상태가 '보유'로 남아 매 완결초 재호출되는 폭주 방지 (재시도 최소간격)
                if n_완결초 - dic_포지션.get('매도시도초', 0) >= _T_매도재시도간격:
                    dic_포지션['매도시도초'] = n_완결초
                    s_사유 = '손절' if b_손절 else '트레일' if b_트레일 else '보유초과' if b_보유초과 else '마감'
                    self._send_매도(s_종목코드=s_종목코드, dic_포지션=dic_포지션, n_초=n_완결초, s_사유=s_사유)

        # 진입 판단 (미보유 시)
        elif dic_포지션['상태'] == '없음':
            n_보유종목수 = sum(1 for p in self.dic_포지션.values() if p['상태'] in ['매수중', '보유', '매도중'])
            n_구간1시작, n_구간1종료 = 9 * 3600, 9 * 3600 + _G1_종료
            b_여력 = (n_완결초 < self.n_장마감초) and (n_보유종목수 < _T_최대보유종목)

            # 구간1 (09:00~09:10) - 절대 체결횟수 + 단가상승 + 매수우위
            b_진입_G1 = (_G1_사용
                       and (n_구간1시작 <= n_완결초 < n_구간1종료)
                       and (n_G1체결률 >= _G1_체결률)
                       and b_G1상승
                       and (n_G1순매수 >= _G1_순매수)
                       and b_여력
                       and (dic_포지션.get('진입횟수G1', 0) < _G1_일최대)
                       and (n_완결초 >= dic_포지션['청산초'] + _G1_쿨다운))
            # 구간2 (09:10~) - 기존 눌림매매. 웜업 360초 경과분만 (기존 판정 시작 조건과 등가)
            b_진입_G2 = ((n_완결초 >= dic_지표['첫초'] + 361)
                       and (n_완결초 >= n_구간1종료 if _G1_사용 else True)
                       and (n_순매수비율 > _T_순매수비율)
                       and (n_거래강도 > _T_거래강도)
                       and (n_전체60 >= _T_최소거래량)      # 절대거래량 바닥 (얇은종목 흔들림 배제)
                       and (n_체결속도 >= _T_체결속도)      # 체결속도 서지 (중간크기 매수의 빠른 연속 = 진짜 상승)
                       and (n_덩어리배수 <= _T_덩어리상한)   # 단일 대형블록 주도(미끼성) 배제
                       and (n_이격률 >= _T_이격최소)
                       and (n_이격률 < _T_이격최대)      # 낙폭과대(칼날) 배제 상한
                       and b_여력
                       and (dic_포지션['진입횟수'] < _T_일최대거래)
                       and (n_완결초 >= dic_포지션['청산초'] + _T_쿨다운))
            if b_진입_G1 or b_진입_G2:
                self._send_매수(s_종목코드=s_종목코드, dic_포지션=dic_포지션, n_초=n_완결초,
                              n_현재가=n_주문참고가, s_구간=('구간1' if b_진입_G1 else '구간2'))

    # -----------------------------------------------------------------
    def _calc_매수금액(self, s_구간='구간2'):
        """ 총자산 균등 주문금액 산정 (진입 신호 시점의 계좌잔고 조회, 백테스팅 _simulate_예수금과 동일)
            총자본   = 예수금(현금) + 전략 보유분 매입원가 합   -> 수동보유 제외·시가 아닌 원가 (백테스팅 폐쇄계와 동일)
            목표금액 = 총자본 ÷ 분할수 (구간1=4 / 구간2=3)     -> 진입마다 총자산의 균등 배분
            리스크캡 = 총자본 × 리스크캡%(1%) ÷ 손절률%       -> 손절 시 손실이 총자본의 1% 이내
            매수금액 = min(목표금액, 리스크캡, 예수금)         -> 균등배분/리스크한계/가용현금 중 최소
            (손절 2% + ÷5 이면 거래당 리스크는 총자본의 0.4%로 캡(1%) 미달 → 캡은 손절>5%에서만 실효)
            잔고 조회 실패 시 폴백 주문금액(_T_주문금액) 사용
            반환: (매수금액, 예수금) - 예수금은 증거금 한도 산정용 """
        try:
            dic_계좌잔고, df_종목별잔고 = self.restapi.tr_체결잔고요청()
            n_예수금 = int(dic_계좌잔고.get('n_d2예수금', 0))
            # 총자본은 전략 보유분만 매입원가로 합산 (수동보유는 제외 - 백테스팅은 전략 포지션만 담는 폐쇄계)
            li_전략종목 = [코드 for 코드, p in self.dic_포지션.items()
                       if p.get('상태') in ['매수중', '보유', '매도중']]
            n_보유원가 = (int(df_종목별잔고.loc[df_종목별잔고['종목코드'].isin(li_전략종목), '매입금액'].sum())
                      if len(df_종목별잔고) > 0 and li_전략종목 else 0)
        except Exception as e:
            self.make_로그(f'잔고 조회 실패 - 폴백 주문금액 {_T_주문금액:,}원 사용 - {e}')
            return _T_주문금액, _T_주문금액
        n_총자본 = n_예수금 + n_보유원가
        if n_총자본 <= 0 or n_예수금 <= 0:
            return 0, n_예수금
        n_분할수 = _G1_분할수 if s_구간 == '구간1' else _T_분할수
        n_목표금액 = n_총자본 / n_분할수 if n_분할수 > 0 else n_총자본   # 분할수 0 방어
        n_리스크캡 = n_총자본 * _T_리스크캡 / 100 / (_T_손절 / 100) if _T_손절 > 0 else n_목표금액
        return int(min(n_목표금액, n_리스크캡, n_예수금)), n_예수금   # 균등배분/리스크한계/가용현금 중 최소

    def _send_매수(self, s_종목코드, dic_포지션, n_초, n_현재가, s_구간='구간2'):
        """ 지정가 매수 주문 송신 (현재가+N호가) - 총자산 균등 사이징
            시장가는 증거금을 상한가 기준으로 과다 예약해 수량이 크게 축소되므로 지정가로 전환.
            지정가는 증거금을 주문단가(현재가+N호가) 기준으로 잡아, 매수금액÷매수단가 수량이 그대로
            주문 가능 → 축소폭 최소화 + 증거금 부족 회피. 현재가보다 N호가 높여 즉시 체결 확률 확보 """
        # 주문수량 산정 - 매수단가(현재가+N호가) 기준 (배분금액·예수금 중 작은 쪽 ÷ 매수단가)
        n_호가수 = _G1_매수호가 if s_구간 == '구간1' else _T_매수호가
        n_매수단가 = self._매수단가(n_현재가, n_호가수=n_호가수)
        n_매수금액, n_예수금 = self._calc_매수금액(s_구간=s_구간)
        n_수량 = int(min(n_매수금액, n_예수금) // n_매수단가) if n_매수단가 > 0 else 0
        if n_수량 < 1:
            self.make_로그(f'매수 보류 - {self._lbl(s_종목코드)} 주문가능수량 0 '
                         f'(매수금액 {n_매수금액:,}원 / 매수단가 {n_매수단가:,}원, 예수금 {n_예수금:,}원)')
            dic_포지션['청산초'] = n_초    # 자금부족 재진입 폭주 방지 (쿨다운 후 재시도)
            return

        # 주문 송신 (IOC 지정가 - 즉시 체결분만 체결하고 잔량 자동 취소, 미체결 주문 잔류 방지)
        res = self.restapi.tr_주식주문(s_구분='매수', s_종목코드=s_종목코드,
                                   n_주문수량=n_수량, n_주문단가=n_매수단가, s_매매구분='IOC보통')

        # 상태 업데이트
        if isinstance(res, dict) and res.get('return_code') == 0:
            dic_포지션.update(상태='매수중', 주문초=n_초, 매수초=n_초, 매수가=n_현재가, 매도재시도=0,
                            주문수량=n_수량, 매도시도초=0, 피크가=n_현재가,   # 피크가=트레일링 고점 시드
                            구간=s_구간)                                  # 청산 규칙은 진입 구간을 따름
            if s_구간 == '구간1':
                dic_포지션['진입횟수G1'] = dic_포지션.get('진입횟수G1', 0) + 1
            else:
                dic_포지션['진입횟수'] += 1
            self.make_로그(f'매수주문[{s_구간}] - {self._lbl(s_종목코드)} '
                         f'{n_수량}주 @{n_매수단가:,}원 (현재가 {n_현재가:,}+{n_호가수}호가, '
                         f'약 {n_수량 * n_매수단가:,}원, IOC지정가)')
            self._save_포지션()
        else:
            s_사유 = res.get('return_msg', res) if isinstance(res, dict) else res
            self.make_로그(f'매수주문 실패 - {self._lbl(s_종목코드)} {n_수량}주 @{n_매수단가:,}원 - {s_사유}')
            dic_포지션['청산초'] = n_초    # 주문거부 재시도 폭주 방지 (쿨다운 후 재시도)

    # -----------------------------------------------------------------
    def _send_매도(self, s_종목코드, dic_포지션, n_초, s_사유):
        """ 시장가 매도 주문 송신 (보유 전량) """
        # 수량 확인
        n_수량 = dic_포지션['수량']
        if n_수량 <= 0:
            dic_포지션['상태'] = '없음'
            return

        # 주문 송신 (IOC 시장가 - 즉시 체결분만 체결하고 잔량 자동 취소, 미체결분은 타임아웃 재시도)
        res = self.restapi.tr_주식주문(s_구분='매도', s_종목코드=s_종목코드,
                                   n_주문수량=n_수량, n_주문단가=0, s_매매구분='IOC시장가')

        # 상태 업데이트
        if isinstance(res, dict) and res.get('return_code') == 0:
            dic_포지션.update(상태='매도중', 주문초=n_초, 매도수량=n_수량)
            self.make_로그(f'매도주문({s_사유}) - {self._lbl(s_종목코드)} {n_수량}주 (IOC시장가)')
            self._save_포지션()
        else:
            s_실패 = res.get('return_msg', res) if isinstance(res, dict) else res
            self.make_로그(f'매도주문 실패 - {self._lbl(s_종목코드)} {n_수량}주 - {s_실패}')

    # -----------------------------------------------------------------
    def _proc_주문체결(self, s_종목코드, dic_값):
        """ 주문체결 수신 처리 - 체결 확인 후 포지션 상태 업데이트 """
        fid = self.fid_주문.dic_이름2코드
        # 종목코드 확인 (FID 우선, 'A' 접두 제거)
        s_코드 = str(dic_값.get(fid['종목코드'], s_종목코드)).strip().lstrip('A')
        if s_코드 not in self.dic_포지션:
            return
        dic_포지션 = self.dic_포지션[s_코드]

        # 체결 상태만 처리
        s_주문상태 = str(dic_값.get(fid['주문상태'], '')).strip()
        if s_주문상태 != '체결':
            return

        # 체결 정보 파싱
        try:
            s_매도수 = self.fid_주문.dic_매도수구분.get(str(dic_값.get(fid['매도수구분'], '')).strip(), '')
            n_체결량 = abs(int(str(dic_값.get(fid['체결량'], '0')).strip() or 0))
            n_체결가 = abs(int(str(dic_값.get(fid['체결가'], '0')).strip() or 0))
            n_미체결 = abs(int(str(dic_값.get(fid['미체결수량'], '0')).strip() or 0))
        except (ValueError, TypeError):
            return

        # 매수 체결 - 보유 확정
        if s_매도수 == '매수' and dic_포지션['상태'] in ['매수중', '보유']:
            # FID 911 체결량은 '누적체결량' → 합산(+=) 말고 최신 누적으로 갱신, 주문수량 상한 (과다누적 방지)
            n_주문수량 = dic_포지션.get('주문수량', 0)
            n_누적체결 = min(n_체결량, n_주문수량) if n_주문수량 > 0 else n_체결량
            dic_포지션['수량'] = max(dic_포지션['수량'], n_누적체결)
            dic_포지션['매수가'] = n_체결가 if n_체결가 > 0 else dic_포지션['매수가']
            dic_포지션['피크가'] = max(dic_포지션.get('피크가', 0), dic_포지션['매수가'])   # 트레일링 고점 시드 보정
            dic_포지션['상태'] = '보유'
            self.make_로그(f'매수체결 - {self._lbl(s_코드)} '
                         f'{n_체결량}주 @{n_체결가:,}원 (보유 {dic_포지션["수량"]}주)')
            self._save_포지션()

        # 매도 체결 - 청산 확정
        elif s_매도수 == '매도' and dic_포지션['상태'] == '매도중':
            # 체결량은 누적매도량 → 매도수량(주문량) 기준으로 잔여 계산 (누적 이중차감 방지)
            n_매도수량 = dic_포지션.get('매도수량', dic_포지션['수량'])
            dic_포지션['수량'] = max(0, n_매도수량 - n_체결량)
            self.make_로그(f'매도체결 - {self._lbl(s_코드)} '
                         f'{n_체결량}주 @{n_체결가:,}원 (잔여 {dic_포지션["수량"]}주)')
            if n_미체결 == 0 or dic_포지션['수량'] == 0:
                n_수익률 = (n_체결가 / dic_포지션['매수가'] - 1) * 100 if dic_포지션['매수가'] > 0 else 0
                dic_포지션.update(상태='없음', 수량=0, 청산초=pd.Timestamp.now().hour * 3600
                                + pd.Timestamp.now().minute * 60 + pd.Timestamp.now().second)
                self.make_로그(f'청산완료 - {self._lbl(s_코드)} '
                             f'수익률 {n_수익률:+.2f}% (비용 전)')
            self._save_포지션()

    # -----------------------------------------------------------------
    async def run_실시간매매(self):
        """ exec 함수들을 비동기로 구동 """
        # 매매대상 선정 및 포지션 복원(재시작 대비) 후 감시 시작
        await self.set_매매대상선정()
        self.restore_포지션()
        await asyncio.gather(
            self.exec_종목감시()
        )


# noinspection SpellCheckingInspection,PyPep8Naming,NonAsciiCharacters
def run(queue_mp_수신2매매=None):
    queue_mp_수신2매매 = queue_mp_수신2매매 if queue_mp_수신2매매 is not None else mp.Queue()
    t = TraderBot(queue_mp_수신2매매=queue_mp_수신2매매)
    asyncio.run(t.run_실시간매매())


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print('\n### [ KeyboardInterrupt detected ] ###')
