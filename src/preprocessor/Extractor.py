import sqlite3
import pandas as pd
from soynlp.noun import LRNounExtractor_v2
from collections import defaultdict
import re
import math
from string import punctuation
from soynlp.word import WordExtractor

# Stopwords 정의
pattern1 = re.compile(r'[{}]'.format(re.escape(punctuation)))  # punctuation 제거
pattern2 = re.compile(r'[^가-힣 ]')  # 특수문자, 자음, 모음, 숫자, 영어 제거
pattern3 = re.compile(r'\s{2,}')  # white space 1개로 바꾸기.


class Ext:
    # Instance를 생성할 때, 데이터 입력.
    def __init__(self, df):
        self.df = df
        self.noun_extractor = LRNounExtractor_v2(verbose=True)
        self.word_extractor = WordExtractor(min_frequency=math.floor(len(self.df) * 0.00001))

    # 위에서 정의한 Stopwords를 이용하여 Data Stopwords 처리
    def cleaning(self):
        self.df['head'] = self.df['head'].map(lambda x: pattern3.sub(' ',
                                                                     pattern2.sub('',
                                                                                  pattern1.sub('', x))))
        return self.df # Stopwords 처리된 data 출력

    # soynlp에서 제공하는 명사 추출을 통해 1차적으로 신어후보 추출
    def extract_nouns(self):
        nouns = self.noun_extractor.train_extract(self.df['head'], min_noun_frequency=math.floor(len(self.df) * 0.00001))
        # 입력받은 data frame에서 명사 추출하며 해당 명사가 전체 게시글 수에서 0.001%이상 등장해야 한다.
        # 뉴스데이터 0.001%, 커뮤니티 데이터 0.01% 이상 등장해야함 
        words = {k: v for k, v in nouns.items() if len(k) > 1}
        # key = 명사(신어후보), value = NounScore로 words라는 dict에 저장
        return words # 1차 신어후보 출력

    # 추출된 신어를 사전에 검색하여 사전에 없는 결과를 2차 신어 후보로 추출
    def search_dict(self, nouns):
        conn = sqlite3.connect('kr_db.db')
        data = pd.read_sql('SELECT word FROM kr_db', conn) # 국립국어원 사전 db를 'data'라는 이름의 data frame으로 저장
        data['word'] = data['word'].map(lambda x: pattern3.sub(' ',
                                                               pattern2.sub('',
                                                                            pattern1.sub('', x))))
        data.drop_duplicates(keep='first', inplace=True)
        data = ' '.join(data['word'])
        # data의 불용어, 중복 게시글 제거 처리를 한뒤 data의 단어를 전부 저장
        return pd.DataFrame([_ for _ in nouns if _[0] not in data]) # 사전에 없는 2차 신어후보 출력

    # 신어후보 단어가 들어가 있는 문장 추출
    def extract_sent(self, words):
        sent = defaultdict(lambda: 0) 
        for w in words[0]:
            temp = [s for s in self.df['head'] if w in s]
            sent[w] = '  '.join(temp)
        # 신어 후보 단어가 있는 문장을 temp에 리스트로 저장하고, sent에 {신어 후보 단어, 예문}으로 저장
        # 예문은 문장을 더블 스페이스로 join하여 sent에 저장   
        return sent # 신어후보가 포함된 문장 출력

    # 각 문장을 기반으로 soynlp에서 제공하는 8가지 변수 추출
    def extract_statistic_value(self, sent):
        statistic = defaultdict(lambda: 0)
        for k, v in sent.items(): # k=신어 후보 단어, v = 예문
            self.word_extractor.train([v]) # 예문에 대한 학습
            try:
                statistic[k] = self.word_extractor.extract()[k] # statistic dict에 key = 신어 후보 단어, value = 8가지 변수로 저장
            except Exception as e:
                print(e)
        return statistic # soynlp에서 제공하는 8가지 변수 출력

    # 각 문장을 기반으로 3가지 변수 추가 추출 
    # (신어후보의 오른쪽에 ~들이 붙은 비율 / 신어후보의 오른쪽에 그 외의 조사가 붙은 비율 / 신어후보의 오른쪽에 white space가 붙은 비율)
    def extract_r_rat(self, sent, statistic):
        conn = sqlite3.connect('kr_db.db')
        post_pos = pd.read_sql('SELECT word FROM kr_db WHERE ID="조사_기초" OR ID="조사_상세"', conn)
        # 검색이 가능한 형태로 만들어주기 위해서 동일한 불용어 처리 (사전의 ~는 과 같이 되어 있는 경우 ~를 제거하기 위함)
        post_pos['word'] = post_pos['word'].map(lambda x: pattern3.sub(' ',
                                                                       pattern2.sub('',
                                                                                    pattern1.sub('', x))))
        post_pos.drop_duplicates(keep='first', inplace=True)
        post_pos = ''.join(post_pos['word']) # 불용어, 중복 처리한 뒤 post_pos에 join하여 합침
        r_rat = defaultdict(lambda: 0) 
        for k in statistic.keys(): # k = 신어후보 단어 
            try:
                self.noun_extractor.train_extract([sent[k]]) # 신어 후보 단어에 대한 예문 학습
                count = pprat = wsrat = pnrat = 0
                for _ in self.noun_extractor.lrgraph.get_r(k, topk=-1): # 신어 후보 단어에 붙는 조사
                    if _[0] == '들': # 신어 후보 단어에 들 조사가 붙으면 pnrat에 들 개수 추가
                        pnrat += _[1]
                    elif _[0] in post_pos: # 신어 후보 오른쪽에 white space가 붙는 경우
                        if _[0] != '':
                            pprat += _[1]
                        elif _[0] == '': # 신어 후보의 오른쪽에 그외 조사가 붙는 경우
                            wsrat = _[1]
                for _ in self.noun_extractor.lrgraph.get_r(k, topk=-1): # 각 신어후보에 대해 조사가 붙는 경우 count
                    count += _[1]

                r_rat[k] = {'rpprat': pprat / count, 'rwsrat': wsrat / count, 'rpnrat': pnrat / count}
            except Exception as e:
                print(e)
        return r_rat # 자체적으로 생성한 3가지 변수 출력

    # 추출한 변수를 하나의 DataFrame으로 합침.
    def combine_var(self, statistic, r_rat):
        statistic = pd.DataFrame().from_dict(statistic).T
        r_rat = pd.DataFrame().from_dict(r_rat).T
        statistic["rpprat"] = r_rat["rpprat"]
        statistic["rwsrat"] = r_rat["rwsrat"]
        statistic['rpnrat'] = r_rat["rpnrat"]
        statistic.rename(columns={0: 'cohesion_forward', 1: 'cohesion_backward', 2: 'left_branching_entropy',
                                  3: 'right_branching_entropy', 4: 'left_accessor_variety', 5: 'right_accessor_variety',
                                  6: 'leftside_frequency', 7: 'rightside_frequency',
                                  'rpprat': 'right_post_postion_ratio', 'rwsrat': 'right_whitespace_ratio', 'rpnrat':'rigt_pluralnouns_ratio'},
                         inplace=True)
        return statistic # 모든 변수를 하나의 DataFrame으로 합쳐서 출력