from os import listdir
from os.path import isfile, join, split
import Queue
import threading
import json
import codecs
import nltk
import requests
import re
from pyquery import PyQuery as pq

# ncbi etuils url
ncbi_service_url = 'http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?' \
                   'db=pubmed&term={}&field=title&retmode=json'
ncbi_pubmed_url = 'https://www.ncbi.nlm.nih.gov/pubmed/?term={}'
ncbi_host = 'https://www.ncbi.nlm.nih.gov'

relation_pos_list = [
                'RB', 'RBR', 'RBS',
                'JJ', 'JJR', 'JJS',
                # 'NN', 'NNS', 'NNP', 'NNPS',
                'VB', 'VBD', 'VBN', 'VBG', 'VBP', 'VBZ']

# list files in a folder and put them in to a queue for multi-threading processing
def multi_thread_process_files(dir_path, file_extension, num_threads, process_func,
                               proc_desc='processed', args=None, multi=None,
                               file_filter_func=None, callback_func=None,
                               thread_wise_objs=None):
    onlyfiles = [f for f in listdir(dir_path) if isfile(join(dir_path, f))]
    num_pdfs = 0
    files = None if multi is None else []
    lst = []
    for f in onlyfiles:
        if f.endswith('.' + file_extension) if file_filter_func is None \
                else file_filter_func(f):
            if multi is None:
                lst.append(join(dir_path, f))
            else:
                files.append(join(dir_path, f))
                if len(files) >= multi:
                    lst.append(files)
                    files = []
            num_pdfs += 1
    if files is not None and len(files) > 0:
        lst.append(files)
    multi_thread_tasking(lst, num_threads, process_func, proc_desc, args, multi, file_filter_func,
                         callback_func,
                         thread_wise_objs=thread_wise_objs)


def multi_thread_tasking(lst, num_threads, process_func,
                               proc_desc='processed', args=None, multi=None,
                               file_filter_func=None, callback_func=None, thread_wise_objs=None):
    num_pdfs = len(lst)
    pdf_queque = Queue.Queue(num_pdfs)
    print('putting list into queue...')
    for item in lst:
        pdf_queque.put_nowait(item)
    thread_num = min(num_pdfs, num_threads)
    arr = [process_func] if args is None else [process_func] + args
    arr.insert(0, pdf_queque)
    print('queue filled, threading...')
    for i in range(thread_num):
        tarr = arr[:]
        thread_obj = None
        if thread_wise_objs is not None and isinstance(thread_wise_objs, list):
            thread_obj = thread_wise_objs[i]
        tarr.insert(0, thread_obj)
        t = threading.Thread(target=multi_thread_do, args=tuple(tarr))
        t.daemon = True
        t.start()

    print('waiting jobs to finish')
    pdf_queque.join()
    print('{0} files {1}'.format(num_pdfs, proc_desc))
    if callback_func is not None:
        callback_func(*tuple(args))


def multi_thread_do(thread_obj, q, func, *args):
    while True:
        p = q.get()
        try:
            if thread_obj is not None:
                func(thread_obj, p, *args)
            else:
                func(p, *args)
        except Exception, e:
            print u'error doing {0} on {1} \n{2}'.format(func, p, str(e))
        q.task_done()


def relation_patterns(s):
    text = nltk.word_tokenize(s)
    pr = nltk.pos_tag(text)
    picked = []
    for p in pr:
        if p[1] in relation_pos_list:
            picked.append(p[0])
    return ' '.join(picked)


def convert_ann_for_training(ann_file, non_hts, hts, out_path):
    anns = None
    with codecs.open(ann_file, encoding='utf-8') as rf:
        anns = json.load(rf)
    p, fn = split(ann_file)
    for ann in anns:
        co = {
                'src': fn,
                'sid': ann['sid'],
                'text': ann['text'],
                'struct': '' if 'struct' not in ann else ann['struct'],
                'sapienta': '' if 'CoreSc' not in ann else ann['CoreSc'],
                'entities': '' if 'ncbo' not in ann else ' '.join( list(set([a['annotation']['text'].lower() for a in ann['ncbo']])) )
              }
        if 'marked' in ann:
            co['marked'] = ann['marked']
            hts.append(co)
        else:
            co['marked'] = ''
            non_hts.append(co)
    print('{} done'.format(ann_file))


def ann_to_training(ann_file_path, output_path):
    non_hts = []
    hts = []
    multi_thread_process_files(ann_file_path, '', 2, convert_ann_for_training,
                               args=[non_hts, hts, output_path], file_filter_func=lambda f: f.endswith('_ann.json'),
                               callback_func=save_sentences)


def save_json_array(lst, file_path):
    with codecs.open(file_path, 'w', encoding='utf-8') as wf:
        json.dump(lst, wf, encoding='utf-8')


def load_json_data(file_path):
    data = None
    with codecs.open(file_path, encoding='utf-8') as rf:
        data = json.load(rf, encoding='utf-8')
    return data

def save_sentences(non_hts, hts, output_path):
    training_testing_ratio = 0.6
    total_num = min(len(hts), len(non_hts))
    trainin_len = int(training_testing_ratio * total_num)
    save_json_array(non_hts, join(output_path, 'full_non_hts.json'))
    save_json_array(hts, join(output_path, 'full_hts.json'))

    save_json_array(non_hts[:trainin_len], join(output_path, 'non_hts.json'))
    save_json_array(hts[:trainin_len], join(output_path, 'hts.json'))
    save_json_array(non_hts[trainin_len:total_num], join(output_path + "/test", 'non_hts.json'))
    save_json_array(hts[trainin_len:total_num], join(output_path + "/test", 'hts.json'))

    # split training data into equally sized groups
    # num_group = 3
    # for i in range(num_group):
    #     s = i * trainin_len / num_group
    #     e = min((i+1) * trainin_len / num_group, trainin_len)
    #     ts = trainin_len + i * (total_num - trainin_len) / num_group
    #     te = min(trainin_len + (i + 1) * (total_num - trainin_len) / num_group, total_num)
    #     save_json_array(non_hts[s:e], join(output_path, 'non_hts' + str(i) +'.json'))
    #     save_json_array(hts[s:e], join(output_path, 'hts' + str(i) +'.json'))
    #     save_json_array(non_hts[ts:te], join(output_path + "/test", 'non_hts' + str(i) +'.json'))
    #     save_json_array(hts[ts:te], join(output_path + "/test", 'hts' + str(i) +'.json'))

    print('all done [training size: {0}, testing size: {1}]'.format(trainin_len, total_num - trainin_len))


def add_pmcid_to_sum(sum_file_path):
    summ = load_json_data(sum_file_path)
    # if 'PMID' in summ:
    #     return
    p, fn = split(sum_file_path)
    m = re.match(r'[^()]+\(\d+\) \- (.+)_annotated_ann\.sum', fn)
    pmcid = None
    journal = None
    if m is not None:
        # ret = json.loads(requests.get(ncbi_service_url.format(m.group(1))).content)
        cnt = requests.get(ncbi_pubmed_url.format(m.group(1))).content
        doc = pq(cnt)

        # check whether it is a list of search results
        results = doc(".result_count.left").eq(0)
        if results.html() is not None:
            dom_str = doc(".rslt > .title").eq(0)
            if dom_str is not None and dom_str.html() is not None:
                pmcid = extract_pubmed(dom_str.html())

            j_elem = doc(".jrnl").eq(0)
            if j_elem is not None and j_elem.html() is not None:
                journal = j_elem.html()
        else:
            dom_str = doc(".rprtid").eq(0)
            if dom_str is not None and dom_str.html() is not None:
                pmcid = extract_pubmed(dom_str.html())
            j_elem = doc(".cit").eq(0)
            if j_elem is not None and j_elem.html() is not None:
                m1 = re.findall(r'alterm="([^"]*)"', str(j_elem.html()))
                if m1 is not None:
                    if len(m1) > 0:
                        journal = m1[0][0:len(m1[0])-1]
        # if p is not None and len(p.strip()) > 0:

        # if ret is None or len(ret['esearchresult']['idlist']) == 0:
        #     print 'no pmc id found for {}'.format(sum_file_path)
        # else:
        #     pmcid = ret['esearchresult']['idlist']
    summ['PMID'] = pmcid
    if journal is not None:
        journal = pq(journal).text()
    summ['journal'] = journal
    print pmcid, journal, sum_file_path
    save_json_array(summ, sum_file_path)


def extract_pubmed(html_str):
    pmcid = None
    m1 = re.findall(u'("/pubmed/(\d+)")|(PMID:</dt>.+XInclude">(\d+)</dd>)', html_str)
    if m1 is not None:
        if len(m1[0][1]) > 0:
            pmcid = m1[0][1]
        elif len(m1[0][3]) > 0:
            pmcid = m1[0][3]
    return pmcid


def process_pmcids(sum_folder):
    multi_thread_process_files(sum_folder, 'sum', 3, add_pmcid_to_sum)


def main():
    # ann_to_training('./anns_v2', './training')
    # sents = [
    #     'The control group was comprised of 15 elderly community dwelling individuals of comparable age and educational background',
    #     'This resulted in data of 172 participants to be included in the present study.'
    # ]
    # relation_patterns(sents[0])
    add_pmcid_to_sum('./summaries/Foster et al., (1986) - Cerebral mapping of apraxia in AD by PET_annotated_ann.sum')
    # process_pmcids('./summaries/')

if __name__ == "__main__":
    main()
