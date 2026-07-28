import os
import sys
import json
import re
import shutil

import pandas as pd
import paramiko

import ut


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection
class FileManager:
    def __init__(self):
        # config 읽어 오기
        self.folder_베이스 = os.path.dirname(os.path.abspath(__file__))
        self.folder_프로젝트 = os.path.dirname(self.folder_베이스)
        self.s_파일명 = os.path.basename(__file__).replace('.py', '')
        dic_config = ut.도구manager.ToolManager().config로딩()

        # 로그 설정
        log = ut.로그maker.LogMaker(s_파일명=self.s_파일명, s_로그명='로그이름_rotator')
        sys.stderr = ut.로그maker.StderrHook(path_에러로그=log.path_에러)
        self.make_로그 = log.make_로그

        # 폴더 정의
        self.dic_폴더정보 = ut.폴더manager.FolderManager().dic_폴더정보
        self.folder_work = dic_config['folder_work']
        self.folder_log = dic_config['folder_log']

        # 기준정보 정의
        self.s_오늘 = pd.Timestamp.now().strftime('%Y%m%d')
        self.li_전체폴더 = self._find_하위폴더(s_기준폴더='folder_work')
        self.dic_config = dic_config

        # 서버정보 정의
        dic_서버정보 = json.load(open(os.path.join(dic_config['folder_설정'], 'server_info.json'), mode='rt', encoding='utf-8'))
        self.dic_서버접속 = dic_서버정보['sftp']
        self.dic_서버폴더 = dic_서버정보['folder']

        # 로그 기록
        self.make_로그(f'구동 시작')

    def update_메인서버(self):
        """ 로컬에 생성된 데이터를 메인서버로 업데이트"""
        # 기준정보 정의
        dic_대상머신 = {'로컬머신': '메인서버'}
        li_제외폴더 = list()
        dic_대상폴더 = {폴더: 폴더 for 폴더 in self.li_전체폴더 if 폴더 not in li_제외폴더}

        # 폴더 동기화
        li_업데이트파일 = list()
        for s_메인폴더, s_보조폴더 in dic_대상폴더.items():
            ret = self._sync_폴더(dic_대상머신=dic_대상머신, s_원본폴더=s_메인폴더, s_타겟폴더=s_보조폴더)
            li_업데이트파일 = li_업데이트파일 + ret

        # 로그 기록
        self.make_로그(f'{len(li_업데이트파일):,.0f}개 파일 업데이트 완료')

    def update_보조서버(self):
        """ 메인서버에 보관된 데이터를 보조서버로 업데이트 """
        # 기준정보 정의
        dic_대상머신 = {'메인서버': '보조서버'}
        dic_대상폴더 = {'데이터/차트수집_tr/일봉': 'ohlcv/일봉',
                    '데이터/차트수집_tr/분봉': 'ohlcv/분봉',
                    '데이터/주식체결_ws': 'tick'}

        # 폴더 동기화
        li_업데이트파일 = list()
        for s_메인폴더, s_보조폴더 in dic_대상폴더.items():
            ret = self._sync_폴더(dic_대상머신=dic_대상머신, s_원본폴더=s_메인폴더, s_타겟폴더=s_보조폴더)
            li_업데이트파일 = li_업데이트파일 + ret

        # 로그 기록
        self.make_로그(f'{len(li_업데이트파일):,.0f}개 파일 업데이트 완료')

    def rotate_보관파일(self):
        """ 로컬머신 대상으로 보관기간 경과된 파일 삭제 """
        # 기준정보 정의
        dic_보관기간 = dict(데이터=self.dic_config['파일보관기간(일)_collector'],
                        매수매도=self.dic_config['파일보관기간(일)_trader'],
                        분석=self.dic_config['파일보관기간(일)_analyzer'])
        li_제외폴더 = list()

        # 메인폴더별 파일 탐색
        for s_메인폴더, s_보관기간 in dic_보관기간.items():
            # 대상폴더 탐색
            li_하위폴더 = self._find_하위폴더(s_기준폴더=s_메인폴더, b_전체폴더명=True)
            li_대상폴더 = [폴더 for 폴더 in li_하위폴더 if 폴더 not in li_제외폴더]

            # 폴더별 삭제대상 파일 탐색
            li_삭제대상 = list()
            s_기준일자 = (pd.Timestamp(self.s_오늘) - pd.DateOffset(days=int(s_보관기간))).strftime('%Y%m%d')
            for folder_대상 in li_대상폴더:
                li_일자파일 = [파일 for 파일 in os.listdir(folder_대상) if len(re.findall(r'\d{8}', 파일)) > 0]
                li_대상파일 = [파일 for 파일 in li_일자파일 if re.findall(r'\d{8}', 파일)[0] < s_기준일자]
                li_삭제대상 = li_삭제대상 + [os.path.join(folder_대상, 파일) for 파일 in li_대상파일]

            # 파일 삭제
            li_삭제용량 = list()
            li_삭제대상_파일 = [파일 for 파일 in li_삭제대상 if os.path.isfile(파일)]
            for path_삭제대상_파일 in li_삭제대상_파일:
                li_삭제용량.append(os.path.getsize(path_삭제대상_파일))
                os.remove(path_삭제대상_파일)

            # 폴더 삭제 - 일자가 포함된 폴더
            li_일자폴더 = [폴더 for 폴더 in li_대상폴더 if len(re.findall(r'\d{8}', 폴더)) > 0]
            li_일자폴더_삭제대상 = [폴더 for 폴더 in li_일자폴더 if re.findall(r'\d{8}', 폴더)[0] < s_기준일자]
            for path_삭제대상_파일 in li_일자폴더_삭제대상:
                try:
                    os.rmdir(path_삭제대상_파일)
                except OSError:
                    pass

            # 로그 기록
            s_삭제용량 = self._cal_단위변경(n_바이트=sum(li_삭제용량))
            self.make_로그(f'{s_메인폴더} 파일 삭제 완료'
                         f' - {s_보관기간}일 - {s_기준일자} 기준 - {len(li_삭제대상):,.0f}개 파일 - {s_삭제용량}')

    # noinspection PyUnresolvedReferences
    def check_잔여공간(self):
        """ 로컬에 남아있는 공간 확인 """
        # 용량 확인
        n_전체, n_사용, n_잔여 = shutil.disk_usage(self.folder_work)

        # 용량 환산
        n_잔여_GB = n_잔여 / (1024 ** 3)
        n_잔여비율 = n_잔여 / n_전체 * 100

        # 잔여공간 부족 시 카톡 송부
        if n_잔여_GB < 20:
            # 카카오 API 연결
            sys.path.append(self.dic_config['folder_kakao'])
            import API_kakao
            kakao = API_kakao.KakaoAPI()

            # 메세지 송부
            s_메세지 = (f'!!! [{self.s_파일명}] !!!\n'
                     f'잔여공간 부족 - {n_잔여_GB:.1f}GB | {n_잔여비율:.0f}%')
            kakao.send_메세지(s_사용자='알림봇', s_수신인='여봉이', s_메세지=s_메세지)

        # 로그 기록
        self.make_로그(f'잔여공간 - {n_잔여_GB:.1f}GB - {n_잔여비율:.0f}%')

    def _find_하위폴더(self, s_기준폴더, b_전체폴더명=False):
        """ 기준폴더 하위에 존재하는 모든 폴더 조회하여 리턴 """
        # 기준정보 정의
        folder_기준 = self.dic_폴더정보[s_기준폴더]

        # 하위폴더 정보 생성
        li_하위폴더 = list()
        for folder_상위, li_폴더명, li_파일명 in os.walk(folder_기준):
            for s_폴더명 in li_폴더명:
                s_폴더명 = os.path.join(folder_상위, s_폴더명)
                s_폴더명_하위 = s_폴더명.replace(f'{folder_기준}/', '')
                li_하위폴더.append(s_폴더명_하위)

        # 전체 폴더명 생성
        if b_전체폴더명:
            li_하위폴더 = [os.path.join(folder_기준, 폴더) for 폴더 in li_하위폴더]
            li_하위폴더 = [folder_기준] + li_하위폴더

        return li_하위폴더

    def _sync_폴더(self, dic_대상머신, s_원본폴더, s_타겟폴더):
        """ 로컬 파일을 서버에 업데이트 """
        # 기준정보 정의
        dic_기준폴더 = dict(로컬머신=self.folder_work,
                            메인서버=self.dic_서버폴더['server_work'], 보조서버=self.dic_서버폴더['server_sub'])
        s_원본머신, s_타겟머신 = list(dic_대상머신.items())[0]
        folder_원본머신 = dic_기준폴더[s_원본머신]
        folder_타겟머신 = dic_기준폴더[s_타겟머신]

        # 대상파일 확인
        folder_원본 = f'{folder_원본머신}/{s_원본폴더}'
        li_파일명 = sorted(파일 for 파일 in os.listdir(folder_원본)
                    if os.path.isfile(os.path.join(folder_원본, 파일)) and not 파일.startswith('.'))

        # 대상파일 미존재 시 종료
        if len(li_파일명) == 0:
            return list()

        # ssh 서버 접속
        li_업데이트파일 = list()
        with paramiko.SSHClient() as ssh:
            # ssh 서버 연결 (알수없는 서버 경고 방지 포함)
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=self.dic_서버접속['hostname'], port=self.dic_서버접속['port'],
                        username=self.dic_서버접속['username'], password=self.dic_서버접속['password'])

            # sftp 세션 시작
            with ssh.open_sftp() as sftp:
                # 파일별 탐색
                for s_파일명 in li_파일명:
                    # 경로 정의
                    path_원본 = f'{folder_원본머신}/{s_원본폴더}/{s_파일명}'
                    path_타겟 = f'{folder_타겟머신}/{s_타겟폴더}/{s_파일명}'

                    # 파일 수정시간 확인
                    n_수정시간_원본, n_수정시간_타겟 = 0, 0
                    if os.path.exists(path_원본):
                        n_수정시간_원본 = int(os.path.getmtime(path_원본)) if s_원본머신 == '로컬머신' else\
                                        sftp.stat(path_원본).st_mtime if s_원본머신 in ['메인서버', '보조서버'] else 0
                    if os.path.exists(path_타겟):
                        n_수정시간_타겟 = int(os.path.getmtime(path_타겟)) if s_타겟머신 == '로컬머신' else\
                                        sftp.stat(path_타겟).st_mtime if s_타겟머신 in ['메인서버', '보조서버'] else 0

                    # 파일 업데이트
                    if n_수정시간_원본 > n_수정시간_타겟:
                        # 폴더 미 존재 시 생성
                        li_폴더명 = f'{folder_타겟머신}/{s_타겟폴더}'.split('/')
                        folder_타겟 = ''
                        for s_폴더명 in li_폴더명:
                            folder_타겟 = folder_타겟 + f'{s_폴더명}/'
                            if not os.path.exists(folder_타겟):
                                sftp.mkdir(folder_타겟)

                        # 파일 업데이트
                        sftp.put(path_원본, path_타겟)

                        # 정보 업데이트
                        li_업데이트파일.append(s_파일명)
                        self.make_로그(f'{s_원본머신} -> {s_타겟머신}\n'
                                     f'- {s_파일명}\n'
                                     f'- /{s_원본폴더} -> /{s_타겟폴더}')

        return li_업데이트파일

    @staticmethod
    def _cal_단위변경(n_바이트):
        """ 입력받은 용량을 단위 변경하여 리턴 """
        # 기준정보 정의
        li_단위 = ['B', 'KB', 'MB', 'GB', 'TB']
        n_단위 = 0

        # 단위 변환
        n_파일사이즈 = n_바이트
        while n_파일사이즈 > 1024:
            n_파일사이즈 = n_파일사이즈 / 1024
            n_단위 = n_단위 + 1

        s_단위 = li_단위[n_단위]
        s_파일사이즈 = f'{n_파일사이즈:.1f}{s_단위}' if s_단위 in ['GB', 'TB'] else f'{n_파일사이즈:.0f}{s_단위}'

        return s_파일사이즈


def run():
    """ 실행 함수 """
    f = FileManager()
    f.update_메인서버()
    # f.update_보조서버()
    f.rotate_보관파일()
    f.check_잔여공간()


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print('\n### [ KeyboardInterrupt detected ] ###')
