"""Cross-modal scope/ID validation, bounded calls and transcript revision invalidation."""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'bin'))
from visual_fixture import observation
from meeting_core import visual_crosscheck as vc
fact={'subject':'收入增长','text':'','raw_value':'18%','value':18.,'unit':'%',
      'period':'Q4','qualifier':'目标','basis':'printed','region':None}
obs={1:observation(facts=[fact])}
pages=[{'page':1,'first':0,'ranges':[[0,10]]}]
turns=[{'start':1,'end':3,'text':'实际增长只有8%'}]
class Client:
    def __init__(self):self.calls=0;self.bad=False
    def complete(self,prompt,**kwargs):
        self.calls+=1
        assert kwargs['response_schema']
        return SimpleNamespace(content=json.dumps({'checks':[{'page':1,'verdict':'different_scope',
            'explanation':'目标与实际不是同一口径','turn_ids':['T999999' if self.bad else 'T000001'],
            'importance':'normal'}]}))
with tempfile.TemporaryDirectory() as tmp:
    client=Client();mdir=Path(tmp)
    result=vc.compare(mdir,turns,pages,obs,client=client)
    assert result['1']['verdict']=='different_scope'
    vc.compare(mdir,turns,pages,obs,client=client)
    assert client.calls==1
    turns[0]['text']='实际增长只有9%'
    vc.compare(mdir,turns,pages,obs,client=client)
    assert client.calls==2
    turns[0]['text']='实际增长10%';client.bad=True
    result=vc.compare(mdir,turns,pages,obs,client=client)
    assert result['1']['verdict']=='pending'
    assert json.loads((mdir/'visual_crosschecks.json').read_text())['pending_pages']==[1]
print('visual crosscheck: scope/evidence validation, cache fencing and failed output stays pending')
try:
    vc.Check.model_validate({'page':1,'verdict':'supported','explanation':'冗长推理'*50,
        'turn_ids':['T000001'],'importance':'normal'})
except ValueError:
    pass
else:
    raise AssertionError('unbounded explanations must not enter the evidence projection')
