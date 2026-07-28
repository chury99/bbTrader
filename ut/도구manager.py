import os
import sys
import re

import pandas as pd
import json
import paramiko


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection,PyUnreachableCode
class ToolManager:
    def __init__(self):
        # 기준폴더 정의
        self.folder_베이스 = os.path.dirname(os.path.abspath(__file__))
        self.folder_프로젝트 = os.path.dirname(self.folder_베이스)

        # 구동 os 확인
        dic_운영체제 = dict(darwin='mac', win32='win', linux='linux')
        self.s_운영체제 = dic_운영체제[sys.platform]

    def config로딩(self):
        """ config.json 파일 확인 후 구동 중인 환경에 맞도록 변수 정의 """
        # config 읽어 오기
        dic_config = json.load(open(os.path.join(self.folder_프로젝트, 'config.json'), mode='rt', encoding='utf-8'))

        # 대상항목 확인
        li_대상항목 = [항목 for 항목 in dic_config.keys() if type(dic_config[항목]) == dict]

        # config 정의
        for s_대상항목 in li_대상항목:
            dic_config[s_대상항목] = dic_config[s_대상항목][self.s_운영체제]

        return dic_config

    @staticmethod
    def df저장(df, path, li_타입=None):
        """ 입력받은 df를 path에 pkl, csv로 저장 """
        # 저장타입 지정
        li_타입 = ['pkl', 'csv'] if li_타입 is None else li_타입

        # pkl 저장
        if 'pkl' in li_타입:
            path_pkl = f'{path}.pkl'
            df.to_pickle(path_pkl)

        # csv 저장
        if 'csv' in li_타입:
            path_csv = f'{path}.csv'
            df.to_csv(path_csv, encoding='cp949', index=False)

    # noinspection PyTypeChecker,PyUnusedLocal
    def sftp파일업로드(self, folder_로컬, s_서버폴더, s_파일명, n_파일보관일수):
        """ sftp 서버 접속 후 해당 파일 업로드 """
        # 서버정보 정의
        dic_서버정보 = json.load(open(os.path.join(self.folder_프로젝트, 'server_info.json'), mode='rt', encoding='utf-8'))
        dic_서버접속 = dic_서버정보['sftp']
        dic_서버폴더 = dic_서버정보['folder']

        # path 정의
        path_로컬 = os.path.join(folder_로컬, s_파일명).replace('\\', '/')
        path_서버 = os.path.join(dic_서버폴더['server_kakao'], s_서버폴더, s_파일명).replace('\\', '/')

        # 서버 접속
        li_복사한파일명 = list()
        li_삭제한파일명 = list()
        with paramiko.SSHClient() as ssh:
            # ssh 서버 연결 (알수없는 서버 경고 방지 포함)
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=dic_서버접속['hostname'], port=dic_서버접속['port'],
                        username=dic_서버접속['username'], password=dic_서버접속['password'])

            # sftp 세션 시작
            with ssh.open_sftp() as sftp:
                # 폴더 생성
                s_서버폴더 = path_서버.replace(s_파일명, '')
                try:
                    sftp_stat = sftp.stat(s_서버폴더)
                except IOError:
                    sftp.mkdir(s_서버폴더)

                # 파일 복사
                ret = sftp.put(path_로컬, path_서버)
                li_복사한파일명.append(s_파일명)

                # 오래된 파일 삭제
                s_파일일자 = re.findall(r'\d{8}', s_파일명)[0]
                s_기준일자 = (pd.Timestamp(s_파일일자) - pd.Timedelta(days=n_파일보관일수)).strftime('%Y%m%d')
                li_삭제파일 = sorted(파일 for 파일 in sftp.listdir(s_서버폴더)
                                 if 파일[0] != '.' and re.findall(r'\d{8}', 파일)[0] < s_기준일자)
                for s_삭제파일 in li_삭제파일:
                    sftp.remove(f'{s_서버폴더}/{s_삭제파일}')
                    li_삭제한파일명.append(s_삭제파일)

        return li_복사한파일명, li_삭제한파일명, dic_서버정보
