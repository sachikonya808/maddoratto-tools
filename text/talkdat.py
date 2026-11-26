# Usage: python talkdat.py Talk.dat talk.json

import struct, json, sys
import collections

LANG={0x10:'ja',0x11:'en',0x12:'zh',0x13:'ko'}
REV={v:k for k,v in LANG.items()}
U32=(6,7,8,9,0x14,0x15)

def load(path):
    d=open(path,'rb').read()
    
    _,cnt,flag=struct.unpack_from('<III',d,0) 
    base=12+cnt*12
    recs=[struct.unpack_from('<III',d,12+i*12) for i in range(cnt)]
    order=sorted(set(r[1] for r in recs))+[len(d)-base] 
    nxt={o:order[j+1] for j,o in enumerate(order[:-1])}
    out=[]
    
    for id_,k,s in recs:
        b=d[base+s:base+nxt[k]]; e={'id':id_,'key':d[base+k:base+s-1].decode(),'pages':[],'_k':k}
        i=0
        
        while i<len(b):
            r=parse_page(b,i)
            if not r: break
            e['pages'].append(r[0]); i=r[1]    
        
        e['end']=b[i:].hex(); out.append(e)
    
    return flag,out

def build(ents,flag=1):
    area=b''; offs={}

    for i in sorted(range(len(ents)),key=lambda i:ents[i].get('_k',i)):
        e=ents[i] 
        key=e['key'].encode()+b'\0'
        offs[i]=(len(area),len(area)+len(key)) 
        area+=key+b''.join(page_bytes(p) for p in e['pages'])+bytes.fromhex(e['end'])
    
    return struct.pack('<III',12,len(ents),flag)+b''.join(struct.pack('<III',e['id'],*offs[i]) for i,e in enumerate(ents))+area

def parse_page(b,i):
    p={'u':{},'text':{v:[] for v in LANG.values()}}
    
    if not(b[i]==1 and struct.unpack_from('<H',b,i+1)[0]==1): 
        return None
    
    p['u']['01']=1; i+=3
    while i<len(b):
        op=b[i]

        if op in U32: 
            p['u']['%02x'%op]=struct.unpack_from('<I',b,i+1)[0]
            i+=5
        elif op in LANG:
            L=struct.unpack_from('<H',b,i+1)[0]; p['text'][LANG[op]].append(b[i+3:i+2+L].decode('utf8')) 
            i+=3+L
        else: 
            break
    
    if b[i:i+5]!=b'\x00\x01\x04\x00\x06': 
        return None
    
    p['foot06']=struct.unpack_from('<I',b,i+5)[0] 
    i+=9
    ft={}
    
    while i<len(b) and b[i] in LANG:
        L=struct.unpack_from('<H',b,i+1)[0] 
        ft.setdefault(LANG[b[i]],[]).append(b[i+3:i+2+L].decode('utf8'))
        i+=3+L
    
    if b[i:i+1]!=b'\x00': return None
    if ft: p['foot_text']=ft
    return p,i+1

def page_bytes(p):
    u=p['u'] 
    b=b'\x01\x01\x00'
    
    for op in (6,7,8,9): 
        if '%02x'%op in u: 
            b+=bytes([op])+struct.pack('<I',u['%02x'%op])
    
    for op,l in LANG.items():
        for s in p['text'][l]:
            r=s.encode('utf8')+b'\0' 
            b+=bytes([op])+struct.pack('<H',len(r))+r
    
    for op in (0x14,0x15):
        if '%02x'%op in u: 
            b+=bytes([op])+struct.pack('<I',u['%02x'%op])
    
    b+=b'\x00\x01\x04\x00\x06'+struct.pack('<I',p['foot06'])
    for op,l in LANG.items():
        for t in p.get('foot_text',{}).get(l,[]):
            r=t.encode('utf8')+b'\0' 
            b+=bytes([op])+struct.pack('<H',len(r))+r
    
    return b+b'\x00'

def to_json(ents): 
    return [{k:v for k,v in e.items() if k!='_k'} for e in ents]

if __name__=='__main__':
    a=sys.argv
    if a[1]=='import':          # import Talk.dat in.json out.dat  (original supplies storage order)
        flag,ents=load(a[2]); j=json.load(open(a[3],encoding='utf8'))
        
        assert len(j)==len(ents)
        for e,x in zip(ents,j): 
            e['pages']=x['pages'] 
            e['end']=x['end']
        
        open(a[4],'wb').write(build(ents,flag)) 
        print('wrote',a[4])
    
    else:
        flag,ents=load(a[1]); orig=open(a[1],'rb').read()
        
        print('entries',len(ents),'byte-exact rebuild:',build(ents,flag)==orig)
        print('pages per entry:',sorted(collections.Counter(len(e['pages']) for e in ents).items()))
        print('non-standard end bytes:',collections.Counter(e['end'] for e in ents).most_common(5))

        if len(a)>2: 
            json.dump(to_json(ents),open(a[2],'w',encoding='utf8'),ensure_ascii=False,indent=1)
