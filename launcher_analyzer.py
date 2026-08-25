import os
import sys
import time

import pandas as pd
import multiprocessing as mp

import analyzer, ut


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection,PyUnreachableCode
class LauncherAnalyzer:
    # noinspection PyUnresolvedReferences
    def __init__(self):
        # config 읽어 오기
        self.folder_프로젝트 = os.path.dirname(os.path.abspath(__file__))
        self.s_파일명 = os.path.basename(__file__).replace('.py', '')
        dic_config = ut.도구manager.ToolManager().config로딩()

        # 로그 설정
        log = ut.로그maker.LogMaker(s_파일명=self.s_파일명, s_로그명='로그이름_analyzer')
        sys.stderr = ut.로그maker.StderrHook(path_에러로그=log.path_에러)
        self.make_로그 = log.make_로그

        # 폴더 정의
        # dic_폴더정보 = ut.폴더manager.FolderManager().dic_폴더정보

        # 기준정보 정의
        self.s_오늘 = pd.Timestamp.now().strftime('%Y%m%d')

        # 카카오 API 연결
        sys.path.append(dic_config['folder_kakao'])
        import API_kakao
        self.kakao = API_kakao.KakaoAPI()

        # 로그 기록
        self.make_로그(f'구동 시작')

    def run_일봉수집(self):
        """ 일봉수집 모듈 실행 - 실시간 모듈 종료 후 바로 진행 """
        # 프로세스 정의
        dic_봇정보 = dict(s_타겟=analyzer.bot_일봉수집.run, s_네임='bot_일봉수집')

        # 프로세스 실행 - 비정상 종료 시 재실행
        dt_에러발생 = pd.Timestamp.now()
        while True:
            # 프로세스 구동
            p_봇 = mp.Process(target=dic_봇정보['s_타겟'], name=dic_봇정보['s_네임'])
            p_봇.start()
            p_봇.join()

            # 종상 종료 시 종료
            if p_봇.exitcode <= 0:
                break

            # 비정상 종료 처리
            else:
                time.sleep(1)
                if pd.Timestamp.now() - dt_에러발생 < pd.Timedelta(seconds=3):
                    break
                else:
                    self.kakao.send_메세지(s_사용자='알림봇', s_수신인='여봉이', s_메세지=f'{p_봇.name} 모듈 재시작')
                    dt_에러발생 = pd.Timestamp.now()

        # 로그 기록
        if p_봇.exitcode <= 0:
            self.make_로그(f'{p_봇.name} 구동 완료')
        else:
            self.send_카톡_오류발생(s_프로세스명=p_봇.name, n_오류코드=p_봇.exitcode)

    def run_종목추천(self):
        """ 종목추천 모듈 실행 """
        # 프로세스 정의
        p_봇 = mp.Process(target=analyzer.bot_종목추천.run, name='bot_종목추천')

        # 프로세스 실행 및 종료 대기
        p_봇.start()
        p_봇.join()

        # 로그 기록
        if p_봇.exitcode <= 0:
            self.make_로그(f'{p_봇.name} 구동 완료')
        else:
            self.send_카톡_오류발생(s_프로세스명=p_봇.name, n_오류코드=p_봇.exitcode)

    def run_백테스팅_틱기반매수세(self):
        """ 틱기반매수세 백테스팅 모듈 실행 - 일봉수집 완료 후 진행 (당일 틱 데이터 검증) """
        # 프로세스 정의
        p_봇 = mp.Process(target=analyzer.bot_백테스팅_틱기반매수세.run, name='bot_백테스팅_틱기반매수세')

        # 프로세스 실행 및 종료 대기
        p_봇.start()
        p_봇.join()

        # 로그 기록
        if p_봇.exitcode <= 0:
            self.make_로그(f'{p_봇.name} 구동 완료')
        else:
            self.send_카톡_오류발생(s_프로세스명=p_봇.name, n_오류코드=p_봇.exitcode)

    def run_대시보드(self):
        """ 대시보드 생성·발송 - 백테스팅 완료 후 진행 (당일 거래내역·종목선정 반영)
            읽기 전용 모듈이라 실패해도 다른 작업에 영향이 없다 (내부에서 예외를 흡수하고 텔레그램으로만 알린다) """
        # 프로세스 정의
        p_봇 = mp.Process(target=analyzer.대시보드.run, name='대시보드')

        # 프로세스 실행 및 종료 대기
        p_봇.start()
        p_봇.join()

        # 로그 기록
        if p_봇.exitcode <= 0:
            self.make_로그(f'{p_봇.name} 구동 완료')
        else:
            self.send_카톡_오류발생(s_프로세스명=p_봇.name, n_오류코드=p_봇.exitcode)

    def ut_파일정리(self):
        """ 파일manager 모듈 실행 """
        # 프로세스 정의
        p_봇 = mp.Process(target=ut.파일manager.run, name='bot_파일정리')

        # 프로세스 실행 및 종료 대기
        p_봇.start()
        p_봇.join()

        # 로그 기록
        if p_봇.exitcode <= 0:
            self.make_로그(f'{p_봇.name} 구동 완료')
        else:
            self.send_카톡_오류발생(s_프로세스명=p_봇.name, n_오류코드=p_봇.exitcode)

    def send_카톡_오류발생(self, s_프로세스명, n_오류코드):
        """ 실행 오류 발생 시 프로세스명 포함하여 카톡 메세지 송부 """
        # 메세지 정의
        s_메세지 = (f'!!! [{self.s_파일명}] !!!\n'
                 f'오류 발생 - {s_프로세스명} | code {n_오류코드}')

        # 메세지 송부
        self.kakao.send_메세지(s_사용자='알림봇', s_수신인='여봉이', s_메세지=s_메세지)


def run():
    """ 실행 함수 """
    l = LauncherAnalyzer()
    l.run_일봉수집()
    l.run_종목추천()
    l.run_백테스팅_틱기반매수세()
    l.run_대시보드()
    l.ut_파일정리()


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print('\n### [ KeyboardInterrupt detected ] ###')
