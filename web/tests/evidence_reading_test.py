"""Server cards consume the selected-language projection without rewriting source."""
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
source=(ROOT/'web/static/app.js').read_text()
names=['readingEvidenceText','readingEvidenceTurn','evidenceOriginal','flowClaim','structureClaimCard']
functions=[]
for name in names:
    start=source.index(f'function {name}(')
    end=source.find('\nfunction ',start+1)
    functions.append(source[start:end])
script='''
const state={uiLanguage:'en',bundle:{evidence:{claims:[{id:'C1',text:'虚构结论',kind:'decision',status:'confirmed',start:3}]},reading_translations:{en:{texts:{'虚构结论':'Synthetic conclusion'},turns:[{index:0,translated_text:'Synthetic excerpt'}]}}}};
const esc=x=>String(x??''),fmt=x=>String(x),isEnglishUi=()=>state.uiLanguage==='en';
const claimAction=()=>null,qualityStatusNames={confirmed:['确认','Confirmed']},qualityKindNames={decision:['决定','Decision']};
'''+ '\n'.join(functions)+'''
for(const render of [flowClaim,structureClaimCard]) {
 const html=render('C1');if(!html.includes('Synthetic conclusion')||html.includes('虚构结论'))throw Error('English card used source text');
}
if(readingEvidenceTurn(0,'source')!=='Synthetic excerpt')throw Error('Evidence turn untranslated');
state.uiLanguage='zh-CN';if(!flowClaim('C1').includes('虚构结论'))throw Error('Source fallback lost');
if(state.bundle.evidence.claims[0].text!=='虚构结论')throw Error('Canonical changed');
'''
subprocess.run(['node','--input-type=commonjs','-e',script],check=True)
print('Server evidence: both card paths, excerpt, language fallback and canonical boundaries passed')
