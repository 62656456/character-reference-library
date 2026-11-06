#!/usr/bin/env python3
"""Portable, read-only library discovery and explicit selected-reference export. No model credentials or inference calls."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_BASE = 'https://62656456.github.io/character-reference-library/'
ROLES = {'portrait':'人物身份与面部','hair':'发型结构','headwear':'发髻与头饰','costume':'完整衣装与鞋履','makeup':'妆容','expression':'整体表情','micro':'局部微动作','body':'身形比例','pose':'动作与重心','skin':'肤色','temperament':'气质','accessory':'配饰','jewelry':'首饰'}
DUTIES = {'portrait':'基础面部身份；明确五官调整优先','hair':'只参考发型，不复制母版脸与衣服','headwear':'只参考发髻、头冠及连接，不复制人物身份','costume':'衣装剪裁、材质、配色与鞋履，穿到人物身上；不采用空身/无人物展示','makeup':'妆容颜色与覆盖位置，不替换人物','expression':'整体神态，不复制母版身份','micro':'局部面部肌肉动作，不替换人物','body':'只参考身体比例，不继承站姿','pose':'关节、重心与接触，不复制人台脸、衣服或画风','skin':'固有肤色深浅与底调，不判断民族或国籍','temperament':'只参考气质，不覆盖所选衣装和动作','accessory':'明确选择的配饰及使用方式','jewelry':'明确选择的首饰及连接结构'}
TRAITS = {'face':'脸型','brows':'眉形','eyes':'眼型','nose':'鼻形','lips':'唇形','age':'成年年龄','gender':'性别','skin':'肤色','undertone':'底调','hair_color':'发色与分区渐变','body':'身形比例','light':'光线','style':'画面风格'}

def fetch(url, maximum=30*1024*1024):
    u=urlsplit(url)
    if u.scheme not in ('https','http') or u.username or u.password:
        raise ValueError('只支持不含登录信息的 HTTP(S) 地址')
    if u.scheme=='http' and u.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('远程地址需要 HTTPS')
    safe=urlunsplit((u.scheme,u.netloc,quote(u.path,safe='/%'),u.query,''))
    with urlopen(Request(safe,headers={'User-Agent':'CharacterReferenceLibrarySkill/1.0'}),timeout=25) as response:
        data=response.read(maximum+1)
        if len(data)>maximum:raise ValueError('内容超过本次读取大小限制')
        return data,response.headers.get_content_type()

def normalize(item):
    out=dict(item)
    for k in ('country','countryIso3','countrySetting','countryIsAuthored','countryFilter','authored_country','nationality'):out.pop(k,None)
    if out.get('source')=='open-reference' and out.get('poseViewCount'):out['category']='动作'
    if out.get('category')=='人像脸型' and (out.get('id','').startswith('country-preui-') or out.get('group')=='国别角色设定'):
        gender='女性' if '女' in str(out.get('gender',out.get('title',''))) else '男性' if '男' in str(out.get('gender',out.get('title',''))) else '人物'
        out['title']='成年'+gender+'肖像 · '+out['id'].replace('country-preui-','')
        out['group']='成年人物肖像'
        out['tags']=[t for t in out.get('tags',[]) if t!='国别角色设定']
    return out

def catalog(args):
    if args.catalog:data=json.loads(Path(args.catalog).read_text(encoding='utf-8-sig'))
    else:data=json.loads(fetch(urljoin(args.base_url.rstrip('/')+'/', '素材目录.json'))[0])
    if not isinstance(data,list):raise ValueError('目录应为条目数组')
    return [normalize(i) for i in data if isinstance(i,dict) and i.get('id') and i.get('reviewStatus') not in ('rejected','淘汰')]

def public_item(item,base):
    fields=['id','title','category','group','description','recipeDescription','tags','gender','age','faceShape','eyeShape','browShape','noseShape','skinTone','undertone','bodyType','temperament','width','height','sourceCredit','usageLicense','licenseUrl','poseViewCount','adultOnly']
    out={k:item[k] for k in fields if k in item}
    for key in ('image','thumbnail'):
        if item.get(key):out[key]=urljoin(base.rstrip('/')+'/',item[key])
    out['detail_url']=base.rstrip('/')+'/#view=gallery&preview='+quote(item['id'])
    out['usage_url']='https://github.com/62656456/character-reference-library/blob/main/ASSET-LICENSE.md'
    return out

def lookup(items,key):
    item=next((i for i in items if i['id']==key),None)
    if not item:raise ValueError('当前目录没有该素材：'+key)
    return item

def clean(value):
    value=str(value or '').replace('盔下没有脸','')
    parts=re.split(r'[。；;]',value)
    return '；'.join(p.strip() for p in parts if p.strip() and not re.search(r'空身|无人物|无可见人台|衣架|底座|不可见支撑|不出现皮肤|领口袖口中空|同一人物.*正面.*背面|供.*参考',p))

def compose(args,items):
    selected=[]
    for value in args.pick:
        role,sep,key=value.partition('=')
        if not sep or role not in ROLES:raise ValueError('--pick 需要 role=asset-id；角色键见 SKILL.md')
        item=lookup(items,key)
        if role=='body' and item.get('category')=='动作':raise ValueError('动作参考请使用 pose；body 只提供身形比例')
        selected.append({'role':role,'label':ROLES[role],'duty':DUTIES[role],'asset':public_item(item,args.base_url)})
    traits=[]
    for value in args.trait:
        key,sep,text=value.partition('=')
        if not sep or key not in TRAITS:raise ValueError('不支持该文字维度；可用：'+', '.join(TRAITS))
        traits.append(TRAITS[key]+'：'+text)
    duo=any(r['role']=='pose' and lookup(items,r['asset']['id']).get('peopleCount')==2 for r in selected)
    descriptions={}
    for value in args.describe:
        role,sep,description=value.partition('=')
        if not sep or role not in ROLES:raise ValueError('--describe 需要 role=已核实的具体外观描述')
        descriptions[role]=description
    missing=[]
    paragraphs=['创作一张完整角色设定图。'+('恰好两位独立的虚构成年人，按所选双人动作互动。' if duo else '一位虚构成年人，只有这一个人物。')]
    for ref in selected:
        item=ref['asset'];role=ref['role'];description=clean(item.get('recipeDescription') or item.get('description') or item['title'])
        if role=='body':description=item.get('bodyType') or item.get('group') or description
        if role=='portrait':
            facts=[str(item[k]) for k in ('gender','age','faceShape','eyeShape','browShape','noseShape','skinTone','temperament') if item.get(k)]
            if not item.get('gender'):
                if '成年女性' in description:facts.insert(0,'成年女性')
                elif '成年男性' in description:facts.insert(0,'成年男性')
            if facts:description='，'.join(facts)
        if role in descriptions:description=clean(descriptions[role])
        if not description or re.fullmatch(r'已生成的?.{0,10}设计|.{0,6}参考',description):
            missing.append({'role':role,'id':item['id'],'thumbnail':item.get('thumbnail'),'reason':'公开文字不足以形成完整无图描述，请看图补充 --describe'})
        paragraphs.append(ref['label']+'：'+description+'。')
    if traits:paragraphs.append('明确调整：'+'；'.join(traits)+'。')
    if args.notes:paragraphs.append('补充要求：'+args.notes)
    paragraphs.append('明确五官设定优先于妆容母版；发型和头饰只影响毛发及饰物，不替换人物身份。动作决定关节、重心和接触，身形参考只决定比例。服装完整穿在人物身上，不复制空身或无脸人台展示。保留头冠、衣摆、鞋履和手势，符合正常人体连接与材质关系。未选眼镜时不自动添加。')
    paragraphs.append('完整头部到脚部入画；背景和光线遵循用户要求，未指定时采用简洁中性背景与柔光。单幅画面，不用拼版代替最终人物。')
    text='\n\n'.join(paragraphs)
    keys=set(args.input if args.input is not None else ('portrait','hair','costume','pose'))
    if not keys.issubset(ROLES):raise ValueError('--input 包含未知角色键')
    inputs=[dict(order=n+1,role=r['role'],id=r['asset']['id'],image=r['asset'].get('image'),duty=r['duty']) for n,r in enumerate(r for r in selected if r['role'] in keys)]
    reference=text+'\n\n计划使用的图片及职责：\n'+'\n'.join('图'+str(r['order'])+'：'+r['id']+'；'+r['duty']+'。' for r in inputs)+'\n未列为图片输入的所选要素仍按完整文字实现。此清单尚未提交给模型。'
    return {'text_prompt':text,'reference_prompt':reference,'selected_assets':selected,'image_inputs':inputs,'input_status':'planned_not_submitted','needs_description':missing,'ready_for_generation':not missing,'generation_executed':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default=DEFAULT_BASE)
    parser.add_argument('--catalog',help='已读取的目录JSON；不修改原文件')
    sub=parser.add_subparsers(dest='command',required=True)
    search=sub.add_parser('search');search.add_argument('query');search.add_argument('--category');search.add_argument('--limit',type=int,default=8)
    inspect=sub.add_parser('inspect');inspect.add_argument('id')
    plan=sub.add_parser('compose');plan.add_argument('--pick',action='append',required=True);plan.add_argument('--trait',action='append',default=[]);plan.add_argument('--describe',action='append',default=[]);plan.add_argument('--input',action='append');plan.add_argument('--notes',default='');plan.add_argument('--out')
    download=sub.add_parser('download');download.add_argument('ids',nargs='+');download.add_argument('--out',required=True)
    args=parser.parse_args();items=catalog(args)
    if args.command=='search':
        words=args.query.casefold().split();matches=[i for i in items if (not args.category or i.get('category')==args.category) and all(w in ' '.join(str(i.get(k,'')) for k in ('id','title','category','group','description','tags','faceShape','gender')).casefold() for w in words)]
        result={'matches':len(matches),'items':[public_item(i,args.base_url) for i in matches[:max(1,min(50,args.limit))]]}
    elif args.command=='inspect':result=public_item(lookup(items,args.id),args.base_url)
    elif args.command=='compose':
        result=compose(args,items)
        if args.out:
            dest=Path(args.out);dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    else:
        refs=[public_item(lookup(items,key),args.base_url) for key in dict.fromkeys(args.ids)]
        folder=Path(args.out);folder.mkdir(parents=True,exist_ok=True);files=[]
        for ref in refs:
            if not re.fullmatch(r'[A-Za-z0-9_-]+',ref['id']):raise ValueError('不安全的素材编号')
            data,mime=fetch(ref['image'],50*1024*1024)
            extension='png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'jpg' if data.startswith(b'\xff\xd8') else 'webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else None
            if not extension:raise ValueError('下载内容不是支持的图片：'+ref['id'])
            dest=folder/(ref['id']+'.'+extension)
            if dest.exists():
                if dest.read_bytes()!=data:raise ValueError('同名文件已存在且不同，未覆盖：'+str(dest))
            else:
                with dest.open('xb') as stream:stream.write(data)
            files.append({'id':ref['id'],'file':str(dest.resolve()),'sha256':hashlib.sha256(data).hexdigest(),'source':ref['image'],'usage_url':ref['usage_url'],'usageLicense':ref.get('usageLicense')})
        result={'downloaded':files,'generation_executed':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    try:main()
    except (ValueError,OSError,KeyError,json.JSONDecodeError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False),file=sys.stderr);sys.exit(1)
