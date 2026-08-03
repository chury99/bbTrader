import os
import sys
import json
import html
import urllib.parse

import requests


# noinspection NonAsciiCharacters,PyPep8Naming,SpellCheckingInspection
class TelegramAPI:
    """ 텔레그램 봇 알림 발송 (xconfig/telegram.json 의 봇 토큰 사용)

        설계 원칙 - 알림은 매매의 부수 기능이므로 어떤 경우에도 호출자를 죽이지 않는다.
          · 설정파일이 없거나 토큰이 비어 있으면 조용히 무시하고 False 를 반환한다
          · 네트워크 오류·타임아웃·API 거부는 전부 내부에서 잡아 로그만 남긴다
          · 모든 요청에 타임아웃을 걸어 장중 매매 루프가 멈추지 않게 한다 """

    S_설정파일 = 'telegram.json'
    N_메세지최대 = 4096          # 텔레그램 sendMessage 본문 길이 상한
    N_타임아웃 = 10              # 기본 요청 타임아웃 (초)

    def __init__(self, folder_설정=None, make_로그=None):
        # 로그 함수 정의 - 주입받지 못하면 표준출력으로 대체 (단독 실행 대비)
        self.make_로그 = make_로그 if make_로그 is not None else (lambda 메세지: print(f'[telegram] {메세지}'))

        # 설정폴더 정의 - 주입받지 못하면 이 파일 기준으로 프로젝트의 xconfig 를 찾는다
        if folder_설정 is None:
            folder_프로젝트 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            folder_설정 = os.path.join(folder_프로젝트, 'xconfig')
        self.folder_설정 = folder_설정

        # 설정 로딩 - bot_token / chat_id 두 항목이 전부
        self.dic_설정 = self._load_설정()
        self.s_토큰 = str(self.dic_설정.get('bot_token', '') or '').strip()
        self.s_chatid = str(self.dic_설정.get('chat_id', '') or '').strip()
        self.n_타임아웃 = int(self.dic_설정.get('타임아웃(초)', self.N_타임아웃))

        # 토큰 자리가 비었거나 안내문구(<...>)만 있으면 미설정 - 발송을 전부 건너뛴다
        self.b_사용 = bool(self.s_토큰) and not self.s_토큰.startswith('<')

    # -----------------------------------------------------------------
    def _load_설정(self):
        """ 설정파일 읽기 - 없으면 빈 dict (알림만 비활성화되고 매매는 정상 동작) """
        path_설정 = os.path.join(self.folder_설정, self.S_설정파일)
        if not os.path.exists(path_설정):
            return dict()
        try:
            with open(path_설정, mode='rt', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            self.make_로그(f'설정파일 읽기 실패 - {self.S_설정파일} ({e})')
            return dict()

    def _s_chatid(self, s_수신인=None):
        """ 수신 대상 결정 - 인자를 주면 그 chat_id, 없으면 설정파일의 기본값 """
        return str(s_수신인).strip() if s_수신인 else self.s_chatid

    def _req(self, s_메서드, dic_데이터=None):
        """ 봇 API 호출 - 성공 시 result, 실패 시 None (예외를 밖으로 던지지 않는다) """
        if not self.b_사용:
            return None
        s_url = f'https://api.telegram.org/bot{self.s_토큰}/{s_메서드}'
        try:
            res = requests.post(s_url, data=dic_데이터, timeout=self.n_타임아웃)
            dic_결과 = res.json()
            if not dic_결과.get('ok'):
                # 토큰은 절대 로그에 남기지 않는다 (설명 문구만 기록)
                self.make_로그(f'{s_메서드} 실패 - {dic_결과.get("error_code")} {dic_결과.get("description")}')
                return None
            return dic_결과.get('result')
        except requests.RequestException as e:
            self.make_로그(f'{s_메서드} 통신 오류 - {type(e).__name__}')
            return None
        except json.JSONDecodeError:
            self.make_로그(f'{s_메서드} 응답 해석 실패')
            return None

    @staticmethod
    def _li_분할(s_본문, n_최대):
        """ 길이 상한을 넘는 본문을 줄 단위로 쪼갠다 (한 줄이 상한을 넘으면 강제 절단) """
        if len(s_본문) <= n_최대:
            return [s_본문]
        li_결과, s_조각 = list(), ''
        for s_줄 in s_본문.split('\n'):
            while len(s_줄) > n_최대:
                if s_조각:
                    li_결과.append(s_조각)
                    s_조각 = ''
                li_결과.append(s_줄[:n_최대])
                s_줄 = s_줄[n_최대:]
            if len(s_조각) + len(s_줄) + 1 > n_최대:
                li_결과.append(s_조각)
                s_조각 = s_줄
            else:
                s_조각 = f'{s_조각}\n{s_줄}' if s_조각 else s_줄
        if s_조각:
            li_결과.append(s_조각)
        return li_결과

    @classmethod
    def s_링크(cls, s_표시이름, s_url):
        """ 주소를 감춘 링크 태그 - 긴 url 대신 파일명만 보이게 한다 (send_메세지 의 HTML 모드용)
            한글 경로는 퍼센트 인코딩하고 표시이름은 HTML 특수문자를 이스케이프한다 """
        if not s_url or not str(s_url).startswith(('http://', 'https://')):
            return html.escape(str(s_표시이름))
        s_주소 = urllib.parse.quote(str(s_url), safe=':/?#[]@!$&\'()*+,;=~-._%')
        return f'<a href="{html.escape(s_주소, quote=True)}">{html.escape(str(s_표시이름))}</a>'

    # -----------------------------------------------------------------
    def send_메세지(self, s_메세지, s_수신인=None, li_링크=None, b_HTML=False):
        """ 텍스트 발송. 길이 상한을 넘으면 여러 건으로 나눠 보낸다.

            li_링크 = [(표시이름, url), ...] 를 주면 본문 끝에 링크를 붙인다.
              주소는 감추고 표시이름만 보이며(눌러서 열림), 이때 본문은 자동으로 HTML 이스케이프된다.
            b_HTML 은 s_메세지 안에 이미 HTML 태그를 직접 넣었을 때만 True 로 준다.

            반환: 전량 발송 성공 여부 """
        if not self.b_사용:
            return False
        s_chatid = self._s_chatid(s_수신인)
        if not s_chatid:
            self.make_로그('chat_id 가 설정되지 않았습니다')
            return False

        s_본문 = str(s_메세지)
        b_HTML모드 = bool(b_HTML or li_링크)
        if li_링크:
            # 본문은 평문이므로 이스케이프하고, 링크만 태그로 붙인다
            s_본문 = s_본문 if b_HTML else html.escape(s_본문)
            s_본문 += '\n\n' + '\n'.join(self.s_링크(이름, url) for 이름, url in li_링크)

        b_성공 = True
        for s_조각 in self._li_분할(s_본문, self.N_메세지최대):
            dic_데이터 = dict(chat_id=s_chatid, text=s_조각)
            if b_HTML모드:
                dic_데이터['parse_mode'] = 'HTML'
                dic_데이터['link_preview_options'] = json.dumps(dict(is_disabled=True))
            if self._req('sendMessage', dic_데이터=dic_데이터) is None:
                b_성공 = False
        return b_성공

    # -----------------------------------------------------------------
    def check_연결(self):
        """ 봇 토큰 유효성 확인 - 성공 시 봇 이름 반환 """
        dic_결과 = self._req('getMe')
        return dic_결과.get('username') if dic_결과 else None

    def check_수신(self, s_수신인=None):
        """ chat_id 유효성 확인 - 메세지를 보내지 않고 대화 정보만 조회 (성공 시 상대 이름) """
        s_chatid = self._s_chatid(s_수신인)
        if not s_chatid:
            return None
        dic_결과 = self._req('getChat', dic_데이터=dict(chat_id=s_chatid))
        if not dic_결과:
            return None
        return (dic_결과.get('title')
                or ' '.join(x for x in [dic_결과.get('first_name'), dic_결과.get('last_name')] if x)
                or dic_결과.get('username') or s_chatid)

    def find_수신인(self):
        """ 봇에게 말을 건 대화 목록에서 chat_id 를 찾아준다 (최초 설정용)
            봇과 먼저 대화를 시작(/start 또는 아무 메세지)해야 목록에 잡힌다 """
        li_업데이트 = self._req('getUpdates')
        if not li_업데이트:
            return list()
        dic_대화 = dict()
        for dic_건 in li_업데이트:
            dic_메세지 = (dic_건.get('message') or dic_건.get('edited_message')
                       or dic_건.get('channel_post') or dict())
            dic_챗 = dic_메세지.get('chat', dict())
            if dic_챗.get('id') is None:
                continue
            s_이름 = (dic_챗.get('title')
                    or ' '.join(x for x in [dic_챗.get('first_name'), dic_챗.get('last_name')] if x)
                    or dic_챗.get('username') or '')
            dic_대화[str(dic_챗['id'])] = dict(chat_id=str(dic_챗['id']),
                                            이름=s_이름, 종류=dic_챗.get('type', ''))
        return list(dic_대화.values())

    def save_chatid(self, s_chatid):
        """ 찾은 chat_id 를 설정파일에 써 넣는다 (bot_token 등 나머지 항목은 건드리지 않는다) """
        path_설정 = os.path.join(self.folder_설정, self.S_설정파일)
        try:
            with open(path_설정, mode='rt', encoding='utf-8') as f:
                dic_원본 = json.load(f)
            dic_원본['chat_id'] = str(s_chatid)
            with open(path_설정, mode='wt', encoding='utf-8') as f:
                json.dump(dic_원본, f, ensure_ascii=False, indent=4)
                f.write('\n')
            self.s_chatid = str(s_chatid)
            return True
        except (OSError, json.JSONDecodeError) as e:
            self.make_로그(f'설정파일 저장 실패 - {type(e).__name__}')
            return False


# noinspection NonAsciiCharacters,PyPep8Naming
def run():
    """ 연결 점검 - python xapi/API_telegram.py [보낼 메세지]

        1) 설정파일·토큰 확인       2) 봇 토큰 유효성(getMe)
        3) chat_id 확인·자동 저장   4) 시험 발송 (인자를 준 경우) """
    api = TelegramAPI()

    path_설정 = os.path.join(api.folder_설정, TelegramAPI.S_설정파일)
    if not os.path.exists(path_설정):
        print(f'설정파일 없음 - {path_설정}')
        print(f'  xconfig/{TelegramAPI.S_설정파일}.example 를 복사해 채운 뒤 다시 실행하세요.')
        return
    if not api.b_사용:
        print(f'bot_token 이 비어 있습니다 - BotFather 에서 발급받아 채우세요.\n  {path_설정}')
        return

    s_봇이름 = api.check_연결()
    if s_봇이름 is None:
        print('봇 토큰이 유효하지 않거나 통신에 실패했습니다.')
        return
    print(f'봇 연결 정상 - @{s_봇이름}')

    # chat_id 확인 - 설정값이 실제로 통하는지 먼저 보고, 안 되면 대화 목록에서 찾아 저장
    s_상대 = api.check_수신() if api.s_chatid else None
    if s_상대:
        print(f'chat_id 정상 - {api.s_chatid} ({s_상대})')
    else:
        if api.s_chatid:
            print(f'설정된 chat_id({api.s_chatid}) 로 대화를 찾을 수 없습니다 - 다시 찾습니다.')
        li_대화 = api.find_수신인()
        if not li_대화:
            print('대화 상대 없음 - 텔레그램에서 봇에게 먼저 아무 메세지나 보낸 뒤 다시 실행하세요.')
            print('  (getUpdates 는 최근 24시간 기록만 돌려줍니다)')
            return
        print('\n봇과 대화 중인 상대')
        for dic_건 in li_대화:
            print(f'  {dic_건["chat_id"]:>16}  {dic_건["이름"]} ({dic_건["종류"]})')
        li_개인 = [건 for 건 in li_대화 if 건['종류'] == 'private'] or li_대화
        if len(li_개인) == 1:
            if api.save_chatid(li_개인[0]['chat_id']):
                print(f'\nchat_id 자동 저장 - {li_개인[0]["chat_id"]} ({li_개인[0]["이름"]})')
        else:
            print('\n대화 상대가 여럿이라 자동 저장하지 않았습니다 - chat_id 를 직접 넣으세요.')
            return

    if len(sys.argv) > 1:
        s_메세지 = ' '.join(sys.argv[1:])
        print(f'\n시험 발송 {"성공" if api.send_메세지(s_메세지=s_메세지) else "실패"} - {s_메세지}')


if __name__ == '__main__':
    run()
