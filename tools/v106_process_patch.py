from pathlib import Path
root=Path('/mnt/data/chess_v106')
p=root/'static/processes.js';s=p.read_text()
needle='''         : `<span class="process-detail">Complete Coaching refresh to create your first evaluation.</span>`}
       <button type="button" class="secondary-button" data-process-action="evaluation" data-command="new" data-job-id="${j.id}" ${!j.benchmark?.versions?.length||isRefreshing(j)?'disabled':''}>Replace model evaluation</button>'''
repl='''         : `<span class="process-detail">No playable evaluation exists yet for ${esc(j.current_coaching_model||'the current model')}. A historical evaluation or stored snapshot is not a new model evaluation.</span>
            <button type="button" class="secondary-button" data-process-action="evaluation" data-command="activate" data-job-id="${j.id}" ${isRefreshing(j)?'disabled':''}>Prepare and open current evaluation →</button>
            ${j.refresh_error ? `<span class="process-error-history">${esc(j.refresh_error)}</span>` : ''}`}
       ${j.evaluation_run ? `<button type="button" class="secondary-button" data-process-action="evaluation" data-command="new" data-job-id="${j.id}" ${isRefreshing(j)?'disabled':''}>Replace ${esc(j.current_coaching_model||'current model')} evaluation</button>` : ''}'''
assert needle in s, 'process substitution anchor missing'
s=s.replace(needle,repl,1)
needle="""    if(command==='new' && kind==='evaluation') {"""
repl="""    if(command==='activate' && kind==='evaluation') {
      busy=true;button.disabled=true;
      if(feedback) feedback.classList.add('hidden');
      try {
        // Never POST to /evaluations here: that endpoint replaces a run.
        const response=await fetch(`/api/jobs/${job}/evaluations/activate`,{
          method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const data=await response.json();
        if (!response.ok) throw new Error(data.error||'The evaluation cannot be opened yet.');
        location.href=data.url;
      } catch(err) {if(feedback){feedback.textContent=err.message;feedback.classList.remove('hidden');}}
      finally {busy=false;await update();}
      return;
    }
    if(command==='new' && kind==='evaluation') {"""
assert needle in s
s=s.replace(needle,repl,1)
p.write_text(s)
print('Process UI now has safe prepare/open action if current model has no run')
