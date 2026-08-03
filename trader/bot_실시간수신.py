import os
import re
import sys
import json

import pandas as pd
import multiprocessing as mp
import asyncio

import ut, xapi


# noinspection NonAsciiCharacters,SpellCheckingInspection,PyPep8Naming,PyTypeChecker,PyAttributeOutsideInit
class TraderBot:
    def __init__(self, queue_mp_수신2저장=None, queue_mp_수신2매매=None):
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
        os.makedirs(self.folder_감시종목, exist_ok=True)

        # 추가 폴더 정의
        self.folder_서버 = ('/Volumes/extSSD4tb/80_Backup/10_python_backup/ProjectWork/spTraderV2'
                          if sys.platform == 'darwin' else '')

        # api 정의
        self.wsapi = xapi.WebsocketAPI_kiwoom.WebsocketAPIkiwoom()
        self.restapi = xapi.RestAPI_kiwoom.RestAPIkiwoom()

        # queue 생성
        self.queue_mp_수신2저장 = queue_mp_수신2저장
        self.queue_mp_수신2매매 = queue_mp_수신2매매

        # 기준정보 정의
        self.s_오늘 = pd.Timestamp.now().strftime('%Y%m%d')

        # 로그 기록
        self.make_로그(f'구동 시작')

    def make_감시종목(self):
        """ 전일일봉 기준으로 감시종목 생성하여 저장 """
        # 일봉 불러오기
        folder_일봉 = os.path.join(self.folder_서버, '데이터', '차트캐시', '일봉1')
        s_기준일자 = max(re.findall(r'\d{8}', 파일)[0] for 파일 in os.listdir(folder_일봉) if '.pkl' in 파일)
        dic_일봉 = pd.read_pickle(os.path.join(folder_일봉, f'dic_차트캐시_1일봉_{s_기준일자}.pkl'))

        # 추가 데이터 불러오기 - 전일 데이터 기준으로 당일 후보종목 생성
        df_거래대상 = pd.read_pickle(os.path.join(self.folder_서버, '데이터', '대상종목', f'df_대상종목_{s_기준일자}.pkl'))
        df_조회순위 = (pd.read_csv(os.path.join(self.folder_서버, '데이터', '조회순위_tr', f'df_조회순위_{s_기준일자}.csv')
                               , encoding='cp949', dtype=str, on_bad_lines='skip'))
        li_거래대상 = df_거래대상['종목코드'].to_list()
        li_조회순위 = df_조회순위['종목코드'].unique().tolist()

        # 감시종목 선정
        li_dic종목선정 = list()
        for s_종목코드, df_일봉 in dic_일봉.items():
            n_종가ma5 = df_일봉['종가ma5'].iloc[-1]
            n_종가ma20 = df_일봉['종가ma20'].iloc[-1]
            n_종가ma120 = df_일봉['종가ma120'].iloc[-1]
            b_거래대상포함 = s_종목코드 in li_거래대상
            b_조회순위포함 = s_종목코드 in li_조회순위
            b_정배열 = n_종가ma5 > n_종가ma20 > n_종가ma120
            dic_종목선정 = df_일봉.iloc[-1].to_dict()
            dic_종목선정.update(거래대상포함=b_거래대상포함, 조회순위포함=b_조회순위포함, 정배열=b_정배열)
            li_dic종목선정.append(dic_종목선정)

        df_종목선정 = pd.DataFrame(li_dic종목선정)
        df_종목선정 = (df_종목선정.sort_values(by=['거래대상포함', '정배열', '조회순위포함', '거래대금(백만)'], ascending=False)
                   .reset_index(drop=True))

        # 감시종목 생성 - 두 키는 감시 100종목을 조회순위 포함 여부로 나눈 것일 뿐, 매매 여부와 무관하다.
        # (실제 매매 유니버스는 실시간매매 set_매매대상선정 / 백테스팅 pick_종목선정이 거래대금·가격으로 따로 뽑는다)
        df_종목선정100 = df_종목선정[:100]
        dic_감시종목 = dict(조회순위포함=df_종목선정100[df_종목선정100['조회순위포함']]['종목코드'].to_list(),
                        조회순위미포함=df_종목선정100[~df_종목선정100['조회순위포함']]['종목코드'].to_list())

        # 파일 저장
        pd.to_pickle(dic_감시종목, os.path.join(self.folder_감시종목, f'dic_감시종목_{self.s_오늘}.pkl'))

        # 로그 기록 - 건수만 (종목코드 목록은 실시간매매 set_매매대상선정에서 기록, 등록 로그와 중복 방지)
        self.make_로그(f'총 {len(df_종목선정100)}개 '
                     f'(조회순위포함 {len(dic_감시종목["조회순위포함"])}개 / 조회순위미포함 {len(dic_감시종목["조회순위미포함"])}개)')

    async def exec_감시종목등록(self):
        """ 감시종목 폴더에 저장된 종목을 웹소켓 서버에 등록 """
        # # 감시종목 생성 - 임시
        # folder = '/Users/ProjectWork/bbTrader/분석/백테스팅/돌파매매/10_종목선정'
        # s_일자 = max(re.findall(r'\d{8}', 파일)[0] for 파일 in os.listdir(folder) if '.pkl' in 파일)
        # df_종목선정 = pd.read_pickle(os.path.join(folder, f'df_종목선정_{s_일자}.pkl'))
        # # df_종목선정 = df_종목선정[df_종목선정['종목선정']]
        # # li_감시종목 = df_종목선정['종목코드'].to_list()
        # # pd.to_pickle(li_감시종목, os.path.join(self.folder_감시종목, f'li_감시종목_{s_일자}.pkl'))
        # dic_감시종목 = dict(조회순위포함=df_종목선정[df_종목선정['종목선정'] & df_종목선정['조회순위포함']]['종목코드'].to_list(),
        #                 조회순위미포함=df_종목선정[df_종목선정['종목선정'] & ~df_종목선정['조회순위포함']]['종목코드'].to_list())
        # pd.to_pickle(dic_감시종목, os.path.join(self.folder_감시종목, f'li_감시종목_{s_일자}.pkl'))

        # 감시종목 불러오기
        s_파일명 = max(파일 for 파일 in os.listdir(self.folder_감시종목)
                    if '.pkl' in 파일 and re.findall(r'\d{8}', 파일)[0] <= self.s_오늘)
        dic_감시종목 = pd.read_pickle(os.path.join(self.folder_감시종목, s_파일명))

        # 감시종목 등록 - 두 키를 합친 100종목 전부가 실시간 수신 대상
        li_감시종목 = dic_감시종목.get('조회순위포함', list()) + dic_감시종목.get('조회순위미포함', list())
        res = await self.wsapi.req_실시간등록(li_종목코드=li_감시종목, li_데이터타입=['주문체결', '주식체결'])

        # 로그 기록
        self.make_로그(f'총 {len(li_감시종목)}개\n'
                     f'{res}')

    async def exec_콘솔(self):
        """ 웹소켓 API에서 수신받은 데이터를 콘솔에 출력 """
        # 루프 구동
        while True:
            # 데이터 수신
            li_데이터 = await self.wsapi.queue_콘솔.get()

            # 데이터 순차 처리
            for dic_데이터 in li_데이터:
                s_데이터타입 = dic_데이터['name']
                s_종목코드 = dic_데이터['item']
                dic_데이터_변동 = dic_데이터['values']

                # 데이터 출력
                print(f'{len(li_데이터)}개 수신 - {s_데이터타입} - {s_종목코드}|{dic_데이터_변동}')

    async def exec_저장(self):
        """ 웹소켓 API에서 수신받은 데이터를 저장 모듈로 전달 """
        # 루프 구동
        while True:
            # 데이터 수신
            li_데이터 = await self.wsapi.queue_저장.get()

            # 데이터 순차 처리
            for dic_데이터 in li_데이터:
                s_데이터타입 = dic_데이터['name']
                s_종목코드 = dic_데이터['item']
                dic_데이터_변동 = dic_데이터['values']

                # 데이터 전달
                self.queue_mp_수신2저장.put(dic_데이터)

    async def exec_매매(self):
        """ 웹소켓 API에서 수신받은 데이터를 매매 모듈로 전달 """
        # 루프 구동
        while True:
            # 데이터 수신
            li_데이터 = await self.wsapi.queue_매매.get()

            # 데이터 순차 처리
            for dic_데이터 in li_데이터:
                s_데이터타입 = dic_데이터['name']
                s_종목코드 = dic_데이터['item']
                dic_데이터_변동 = dic_데이터['values']

                # 데이터 전달
                self.queue_mp_수신2매매.put(dic_데이터)

    async def run_실시간수신(self):
        """ exec 함수들을 비동기로 구동 """
        # 웹소켓 서버 접속 및 수신대기 (연결 끊김 시 자동 재접속)
        self.wsapi.b_자동재접속 = True
        await self.wsapi.ws_서버접속()
        task_수신대기 = asyncio.create_task(self.wsapi.ws_수신관리())
        await asyncio.sleep(1)

        # task 활성화
        await asyncio.gather(
            task_수신대기,
            self.exec_감시종목등록(),
            self.exec_콘솔(),
            self.exec_저장(),
            self.exec_매매()
        )


# noinspection SpellCheckingInspection,PyPep8Naming,NonAsciiCharacters
def run(queue_mp_수신2저장=None, queue_mp_수신2매매=None):
    queue_mp_수신2저장 = queue_mp_수신2저장 if queue_mp_수신2저장 is not None else mp.Queue()
    queue_mp_수신2매매 = queue_mp_수신2매매 if queue_mp_수신2매매 is not None else mp.Queue()
    t = TraderBot(queue_mp_수신2저장=queue_mp_수신2저장, queue_mp_수신2매매=queue_mp_수신2매매)
    t.make_감시종목()
    asyncio.run(t.run_실시간수신())


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print('\n### [ KeyboardInterrupt detected ] ###')
