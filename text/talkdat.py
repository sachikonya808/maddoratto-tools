# Usage: python talkdat.py Talk.dat talk.json

import struct, json, sys

LANG={0x10:'ja',0x11:'en',0x12:'zh',0x13:'ko'}

def load(path):
    d=open(path,'rb').read()
    
    rs,cnt,flag=struct.unpack_from('<III',d,0); assert rs==12
    base=12+cnt*12
    recs=[struct.unpack_from('<III',d,12+i*12) for i in range(cnt)]
    out=[]
    
    order=sorted(set(r[1] for r in recs))+[len(d)-base]
    nxt={o:order[j+1] for j,o in enumerate(order[:-1])}
    
    for i,(id_,k,s) in enumerate(recs):
        end=nxt[k]
        key=d[base+k:base+s-1].decode()
        body=d[base+s:base+end]
        e={'id':id_,'key':key,'u':{},'text':{v:[] for v in LANG.values()}}
        i2=0
        
        while i2<len(body):
            op=body[i2]
            if op==1: e['u']['01']=struct.unpack_from('<H',body,i2+1)[0]; i2+=3
            elif op in(6,7,8,9,0x14,0x15): e['u']['%02x'%op]=struct.unpack_from('<I',body,i2+1)[0]; i2+=5
            elif op in LANG:
                L=struct.unpack_from('<H',body,i2+1)[0]
                e['text'][LANG[op]].append(body[i2+3:i2+2+L].decode('utf8')); i2+=3+L
            else: break
        
        e['tail']=body[i2:].hex(); e['_k']=k
        e['_body']=body
        
        out.append(e)
    
    return d[:12],flag,out

def dump_body(e):
    b=b''
    u=e['u']

    if '01' in u: b+=b'\x01'+struct.pack('<H',u['01'])
    
    for op in ('06','07','08','09'):
        if op in u: b+=bytes([int(op,16)])+struct.pack('<I',u[op])
    
    for op,l in LANG.items():
        for s in e['text'][l]:
            r=s.encode('utf8')+b'\0'; b+=bytes([op])+struct.pack('<H',len(r))+r
    
    for op in ('14','15'):
        if op in u: b+=bytes([int(op,16)])+struct.pack('<I',u[op])
    
    return b+bytes.fromhex(e['tail'])

def build(ents,flag=1):
    n=len(ents); area=b''; offs={}
    
    for i in sorted(range(n),key=lambda i:ents[i].get('_k',i)):   # storage order = original key_off order
        e=ents[i]; key=e['key'].encode()+b'\0'
        offs[i]=(len(area),len(area)+len(key)); area+=key+dump_body(e)
    
    heads=b''.join(struct.pack('<III',e['id'],*offs[i]) for i,e in enumerate(ents))
    
    return struct.pack('<III',12,n,flag)+heads+area

if __name__=='__main__':
    hdr,flag,ents=load(sys.argv[1])
    orig=open(sys.argv[1],'rb').read()
    print('entries',len(ents),'byte-exact rebuild:',build(ents,flag)==orig)
    
    bad=[e['key'] for e in ents if dump_body(e)!=e['_body']]
    print('bodies differing',len(bad),bad[:5])
    
    if len(sys.argv)>2:
        json.dump([{k:v for k,v in e.items() if k not in('_body','_k')} for e in ents],open(sys.argv[2],'w',encoding='utf8'),ensure_ascii=False,indent=1)
