
from pathlib import Path
from datetime import datetime,timezone
import subprocess,json,hashlib
d=Path(__file__).resolve().parent
state={'status':'downloading_official_uv_archive','pid':__import__('os').getpid(),'model_calls':0,'url':'https://github.com/astral-sh/uv/releases/download/0.9.5/uv-x86_64-unknown-linux-gnu.tar.gz'}
def save(**v):state.update(v,checked_at=datetime.now(timezone.utc).isoformat());(d/'status.json').write_text(json.dumps(state,indent=2))
try:
 save();p=subprocess.run(['curl','-fLsS','--connect-timeout','5','--max-time','30','-o',str(d/'uv.tar.gz.partial'),state['url']],capture_output=True,timeout=35)
 assert p.returncode==0,p.stderr.decode(errors='replace')[-200:]
 pth=d/'uv.tar.gz.partial';assert pth.stat().st_size>1000000;pth.rename(d/'uv.tar.gz')
 with (d/'uv.tar.gz').open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 save(status='official_archive_downloaded',archive=str(d/'uv.tar.gz'),sha256=digest,bytes=(d/'uv.tar.gz').stat().st_size)
except BaseException as e:save(status='failed',error=str(e));raise
