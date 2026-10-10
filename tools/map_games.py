import sys,os,pickle,json,hashlib; sys.path.insert(0,os.path.expanduser("~/dev/rhythmheavenrecomp/tools"))
from rhplay import Session, find_tiles, tile_hash
home=os.path.expanduser("~")
BASE=f"{home}/dev/rh-build/fz-menu2.state"
s=Session(f"{home}/dev/rh-build/runner-play4/nds_runner", f"{home}/dev/rh-build/rh.nds", f"{home}/dev/rh-build/run-fz", save=f"{home}/dev/rh-build/fz.sav")
s.load_state(BASE); s.run(40)
w,h,rgb=s.grab()[1]
def crop(rgb,cx,cy,r=10):
    return b"".join(rgb[((cy+j)*w+cx-r)*3:((cy+j)*w+cx+r)*3] for j in range(-r,r))
TEMPLATE=crop(rgb,22,30)
def handle_at(w,h,rgb,tiles):
    best=(0,None)
    rows={}
    for (x,y) in tiles: rows.setdefault(y,[]).append(x)
    for y,xs in rows.items():
        x0=min(xs); 
        for dx in (41,):
            cx=x0-dx
            if cx<10 or cx>w-10: continue
            c=crop(rgb,cx,y)
            m=sum(1 for i in range(0,len(c),3) if c[i:i+3]==TEMPLATE[i:i+3])/(len(c)//3)
            if m>best[0]: best=(m,(cx,y))
    return best
def drag(hx,hy,dx,dy):
    x1=max(8,min(247,hx+dx)); y1=max(8,min(184,hy+dy))
    s.flick(hx,hy,x1,y1,22); s.run(80)
sid=0; states={}  # sid -> dict(state_file, tiles)
seen_tiles={}     # hash -> (sid, (cx,cy))
queue=[(0,BASE)]
sigs=set()
moves=[(170,0),(-170,0),(0,120),(0,-120)]
out=[]
def record(sid,path):
    w,h,rgb=s.grab()[1]
    tiles=find_tiles(w,h,rgb)
    hs=[tile_hash(w,h,rgb,*t) for t in tiles]
    sig=hashlib.sha1("".join(sorted(hs)).encode()).hexdigest()
    return tiles,hs,sig,handle_at(w,h,rgb,tiles)
tiles,hs,sig,hd=record(0,BASE); sigs.add(sig)
states[0]=dict(path=BASE,tiles=tiles,hashes=hs,handle=hd[1],score=hd[0])
for t,hh in zip(tiles,hs): seen_tiles.setdefault(hh,(0,t))
print("state0 handle",hd)
frontier=[0]
while frontier and len(states)<40:
    cur=frontier.pop(0)
    st=states[cur]
    for mv in moves:
        s.load_state(st["path"]); s.run(5)
        hx,hy=st["handle"]
        drag(hx,hy,*mv)
        tiles,hs,sig,hd=record(len(states),None)
        # realised shift from tiles present before and after
        before={}
        for t,hh in zip(st["tiles"],st["hashes"]): before.setdefault(hh,[]).append(t)
        diffs=[]
        for t,hh in zip(tiles,hs):
            if hh in before and len(before[hh])==1:
                bx,by=before[hh][0]; diffs.append((t[0]-bx,t[1]-by))
        if diffs:
            dxs=sorted(d[0] for d in diffs); dys=sorted(d[1] for d in diffs)
            shift=(dxs[len(dxs)//2],dys[len(dys)//2])
        else:
            shift=(max(8,min(247,hx+mv[0]))-hx, max(8,min(184,hy+mv[1]))-hy)
        nh=(hx+shift[0],hy+shift[1])
        hd=(1.0,nh)
        if sig in sigs: continue
        sigs.add(sig); nid=len(states)
        p=f"{home}/dev/rh-build/map-{nid}.state"; s.save_state(p)
        states[nid]=dict(path=p,tiles=tiles,hashes=hs,handle=hd[1],score=hd[0],parent=cur,move=mv)
        new=0
        for t,hh in zip(tiles,hs):
            if hh not in seen_tiles: seen_tiles[hh]=(nid,t); new+=1
        print(f"state {nid} from {cur} {mv}: tiles={len(tiles)} new={new} handle={hd} total_unique={len(seen_tiles)}",flush=True)
        frontier.append(nid)
json.dump({"states":{k:{kk:vv for kk,vv in v.items()} for k,v in states.items()},"tiles":{k:list(v) for k,v in seen_tiles.items()}},open(f"{home}/dev/rh-build/map.json","w"))
s.close()
