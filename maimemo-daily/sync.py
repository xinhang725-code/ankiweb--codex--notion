#!/usr/bin/env python3
"""每天从真实考研原文核查过的队列向墨墨写入10个搭配；失败时不虚报成功。"""
import json, os, re, sys, time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

DATA = Path(__file__).resolve().parent / 'data'
BASE = 'https://open.maimemo.com/open/api/v1'
TITLE = '考研真题高频搭配'

class ApiError(Exception):
    def __init__(self, code, path):
        super().__init__(f'墨墨 API 错误：HTTP {code}，接口 {path}')
        self.code = code

class Client:
    def __init__(self):
        self.token = os.environ.get('MAIMEMO_TOKEN', '')
        if not self.token:
            raise ValueError('缺少 MAIMEMO_TOKEN GitHub Actions Secret')
        self.last = 0.0

    def call(self, method, path, query=None, payload=None):
        url = BASE + path + ('?' + urlencode(query) if query else '')
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        for attempt in range(5):
            remaining = 1.6 - (time.monotonic() - self.last)
            if remaining > 0: time.sleep(remaining)
            self.last = time.monotonic()
            req = Request(url, data=data, method=method,
                headers={'Authorization': 'Bearer ' + self.token,
                         'Content-Type': 'application/json',
                         'Accept': 'application/json'})
            try:
                with urlopen(req, timeout=30) as r:
                    content = r.read()
                    result = json.loads(content) if content.strip() else {}
                    if not isinstance(result, dict):
                        raise RuntimeError('API 数据格式异常')
                    return result
            except HTTPError as err:
                status = err.code
                err.close()
                if (status == 429 or status >= 500) and attempt < 4:
                    time.sleep(min(2 ** (attempt + 1), 30))
                    continue
                raise ApiError(status, path) from None
            except URLError:
                if attempt < 4:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError('无法连接墨墨 API') from None
        raise RuntimeError('API 重试上限已到')

    def voc_id(self, spelling):
        try:
            res = self.call('GET', '/vocabulary', {'spelling': spelling})
            voc = res.get('voc') or {}
            return voc.get('id') if isinstance(voc, dict) else None
        except ApiError as e:
            if e.code in (400, 404, 422): return None
            raise

    def note(self, voc_id, entry):
        marker = '[考研搭配:' + entry['id'] + ']'
        notes = self.call('GET', '/notes', {'voc_id': voc_id}).get('notes', [])
        if not isinstance(notes, list):
            raise RuntimeError('助记列表格式异常')
        if any(marker in (note.get('note') or '') and note.get('status') != 'DELETED'
               for note in notes if isinstance(note, dict)):
            return '已存在'
        body = {'note': {
            'voc_id': voc_id, 'note_type': '固定搭配',
            'note': '\n'.join((
                marker, entry['phrase'] + ' — ' + entry['meaning'],
                '真题片段：' + entry['quote'], '来源：' + entry['source'],
                '辨析：' + entry.get('tip', '注意上下文')))}}
        res = self.call('POST', '/notes', payload=body)
        if not isinstance(res.get('note'), dict) or not res['note'].get('id'):
            raise RuntimeError('新增助记没有返回 ID，暂不计入成功')
        return '新增'

    def custom_details(self, voc_id, entry):
        """词典缺少完整短语时，把自定义释义和真题例句挂到核心单词词条。"""
        marker = '[考研搭配:' + entry['id'] + ']'
        definition = marker + ' ' + entry['phrase'] + '：' + entry['meaning']
        rows = self.call('GET', '/interpretations', {'voc_id': voc_id}).get('interpretations', [])
        if not isinstance(rows, list):
            raise RuntimeError('自定义释义列表格式异常')
        if not any(marker in (x.get('interpretation') or '') and x.get('status') != 'DELETED'
                   for x in rows if isinstance(x, dict)):
            response = self.call('POST', '/interpretations', payload={'interpretation': {
                'voc_id': voc_id, 'interpretation': definition,
                'tags': ['考研', '简明'], 'status': 'PUBLISHED'}})
            if not isinstance(response.get('interpretation'), dict) or not response['interpretation'].get('id'):
                raise RuntimeError('自定义释义未返回 ID')
        examples = self.call('GET', '/phrases', {'voc_id': voc_id}).get('phrases', [])
        if not isinstance(examples, list):
            raise RuntimeError('真题例句列表格式异常')
        if not any(x.get('phrase') == entry['quote'] and x.get('origin') == entry['source']
                   for x in examples if isinstance(x, dict)):
            response = self.call('POST', '/phrases', payload={'phrase': {
                'voc_id': voc_id, 'phrase': entry['quote'],
                'interpretation': entry['meaning'], 'tags': ['考研', '短语'],
                'origin': entry['source']}})
            if not isinstance(response.get('phrase'), dict) or not response['phrase'].get('id'):
                raise RuntimeError('真题例句未返回 ID')

    def book(self):
        for offset in range(0, 2000, 100):
            rows = self.call('GET', '/notepads', {'limit': 100, 'offset': offset}).get('notepads', [])
            if not isinstance(rows, list): raise RuntimeError('词本列表格式异常')
            for row in rows:
                if row.get('title') == TITLE and row.get('status') != 'DELETED' and row.get('type') == 'NOTEPAD':
                    doc = self.call('GET', '/notepads/' + quote(str(row['id']), safe='')).get('notepad')
                    if not isinstance(doc, dict) or 'content' not in doc:
                        raise RuntimeError('词本详情格式异常')
                    return doc
            if len(rows) < 100: break
        payload = {'notepad': {'title': TITLE, 'brief': '历年真题搭配，中文及来源请查看助记',
                                'content': '# 考研真题搭配\n', 'tags': ['考研'],
                                'status': 'PUBLISHED'}}
        doc = self.call('POST', '/notepads', payload=payload).get('notepad')
        if not isinstance(doc, dict) or not doc.get('id'):
            raise RuntimeError('创建云词本失败')
        doc.setdefault('content', payload['notepad']['content'])
        return doc

    def add_book_words(self, doc, entries, day):
        original = doc['content']
        known = {s.strip().casefold() for s in original.splitlines()
                 if s.strip() and not s.lstrip().startswith('#')}
        new = []
        for entry in entries:
            word = entry['_word']
            if word.casefold() not in known:
                new.append(word)
                known.add(word.casefold())
        if not new: return 0
        content = original.rstrip() + '\n\n# ' + day + '\n' + '\n'.join(new) + '\n'
        body = {'notepad': {'title': doc.get('title') or TITLE,
                'brief': doc.get('brief') or '考研真题搭配',
                'content': content, 'tags': doc.get('tags') or ['考研'],
                'status': 'PUBLISHED'}}
        out = self.call('POST', '/notepads/' + quote(str(doc['id']), safe=''), payload=body)
        if not isinstance(out.get('notepad'), dict):
            raise RuntimeError('更新云词本没有成功确认')
        return len(new)

def load(name, fallback):
    path = DATA / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else fallback

def save(state):
    dest = DATA / 'state.json'
    tmp = DATA / 'state.json.tmp'
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(dest)

def valid(x):
    fields = ['id', 'phrase', 'headword', 'meaning', 'quote', 'source']
    return (isinstance(x, dict) and
            all(isinstance(x.get(k), str) and x[k].strip() for k in fields) and
            re.fullmatch(r'[a-zA-Z0-9_-]{4,100}', x['id']) is not None and
            re.fullmatch(r"[a-zA-Z][a-zA-Z'-]*", x['headword']) is not None and
            x['phrase'].casefold() in x['quote'].casefold())

def main():
    day = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d')
    state = load('state.json', {'days': {}, 'entries': {}, 'phrases': {}})
    for key in ['days', 'entries', 'phrases']: state.setdefault(key, {})
    done = state['days'].get(day, [])
    if len(done) >= 10:
        print(f'{day} 已完成 {len(done)} 条，重复运行不再写入')
        return 0
    entries = load('queue.json', []) + load('seed.json', [])
    options = []
    seen = set(state['phrases'])
    seen_ids = set()
    for x in entries:
        if not valid(x):
            print('跳过不合法条目：真题片段必须包含原搭配')
            continue
        phrase = x['phrase'].strip().casefold()
        if x['id'] not in state['entries'] and x['id'] not in seen_ids and phrase not in seen:
            options.append(x); seen.add(phrase); seen_ids.add(x['id'])
    need = 10 - len(done)
    if len(options) < need:
        print(f'真题候选不足：还差 {need} 条，现有 {len(options)} 条。请补充 queue.json')
        return 2
    api = Client()
    doc = api.book()
    processed = []
    for x in options:
        if len(processed) >= need: break
        try:
            word = x['phrase']
            voc_id = api.voc_id(word)
            if not voc_id:
                word = x['headword']
                voc_id = api.voc_id(word)
            if not voc_id:
                print('未找到核心词词条：' + x['id'])
                continue
            result = api.note(voc_id, x)
            if word.casefold() != x['phrase'].casefold():
                api.custom_details(voc_id, x)
            processed.append(dict(x, _word=word))
            print('已核实并写入：' + x['phrase'] + '（' + result + '）')
        except ApiError as e:
            if e.code in (401, 403): raise
            print('跳过条目 ' + x['id'] + '：' + str(e))
    if not processed: return 3
    word_count = api.add_book_words(doc, processed, day)
    for x in processed:
        state['entries'][x['id']] = {'day': day, 'phrase': x['phrase'], 'word': x['_word']}
        state['phrases'][x['phrase'].strip().casefold()] = x['id']
        state['days'].setdefault(day, []).append(x['id'])
    save(state)
    print(f'{day}：已入库 {len(processed)} 条，词本新增 {word_count} 词项，当日累计 {len(state["days"][day])}/10')
    return 0 if len(state['days'][day]) == 10 else 4

if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as e:
        print('入库失败：' + str(e), file=sys.stderr)
        sys.exit(1)
