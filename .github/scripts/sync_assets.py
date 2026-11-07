import hashlib,json,os,re,subprocess,urllib.request,zipfile
from pathlib import Path
root=Path.cwd().resolve();manifest=json.loads((root/'.github/releases/current-assets.json').read_text());work=Path(os.environ['RUNNER_TEMP'])/'atlas-packages';work.mkdir(exist_ok=True)
expected={i['path']:i for i in manifest['files']};written=[]
for package in manifest['packages']:
    target=work/package['file']
    subprocess.run(['gh','release','download',manifest['tag'],'--repo',os.environ['GITHUB_REPOSITORY'],'--pattern',package['file'],'--dir',str(work)],check=True)
    if hashlib.sha256(target.read_bytes()).hexdigest()!=package['sha256']:raise RuntimeError('Package checksum mismatch')
    with zipfile.ZipFile(target) as archive:
        for member in archive.infolist():
            name=member.filename
            if not re.fullmatch(r'media/(originals|previews)/[A-Za-z0-9_-]+\.(png|webp|jpg|jpeg)',name) or name not in expected:raise RuntimeError('Unexpected package path')
            data=archive.read(member);row=expected[name]
            if hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()!=row['sha']:raise RuntimeError('Image content differs')
            previous=subprocess.check_output(['git','ls-tree','HEAD','--',name],text=True).strip();old=previous.split()[2] if previous else None
            if old not in [None,row['sha'],row.get('beforeSha')]:raise RuntimeError('Concurrent image modification: '+name)
            destination=(root/name).resolve()
            if not destination.is_relative_to(root):raise RuntimeError('Unsafe destination')
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data);written.append(name)
    print('Verified and extracted',package['file'],flush=True)
if set(written)!=set(expected):raise RuntimeError('Missing image paths')
paths=work/'staged-paths';paths.write_bytes(b''.join(p.encode()+b'\0' for p in written))
subprocess.run(['git','add','--sparse','--pathspec-from-file='+str(paths),'--pathspec-file-nul'],check=True)
if subprocess.run(['git','diff','--cached','--quiet']).returncode:
    subprocess.run(['git','config','user.name','github-actions[bot]'],check=True);subprocess.run(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],check=True)
    subprocess.run(['git','commit','-m','Publish verified character-reference images for '+manifest['tag']],check=True)
    subprocess.run(['git','push','origin','HEAD:main'],check=True)
else:print('Images already current')
