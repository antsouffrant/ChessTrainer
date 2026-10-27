from pathlib import Path
root=Path('/mnt/data/chess_v106')
p=root/'app.py';s=p.read_text()
needle="""                    history = run_history(conn, row['id'],COACHING_VERSION)
                    item['evaluation_run'] = history[0] if history else None
                    item['current_coaching_model'] = COACHING_VERSION"""
repl="""                    history = run_history(conn, row['id'])
                    current_runs = [r for r in history if r['coaching_version'] == COACHING_VERSION]
                    item['evaluation_run'] = current_runs[0] if current_runs else None
                    item['frozen_evaluations'] = [r for r in history if r['coaching_version'] != COACHING_VERSION]
                    item['current_coaching_model'] = COACHING_VERSION"""
assert needle in s
s=s.replace(needle,repl,1)
p.write_text(s)
p=root/'static/processes.js';s=p.read_text()
s=s.replace("  let busy = false;", "  let busy = false;\n  let evaluationErrorMessage = '';",1)
needle='''       <span>${fmt(cohort.versions?.length||0)} completed model snapshots · ${fmt(cohort.available)} positions available</span>'''
repl='''       <span>Current model: ${esc(j.current_coaching_model||'unknown')} · ${fmt(cohort.available)} of ${fmt(cohort.size)} benchmark positions available</span>
       ${(j.frozen_evaluations||[]).map(r=>`<span class="process-detail"><i class="fa-solid fa-lock" aria-hidden="true"></i> Historical ${esc(r.coaching_version)} · ${fmt(r.solved)}/${fmt(r.total)} completed · locked · <a href="/coach/benchmark?job_id=${j.id}">View in Coach</a></span>`).join('')}'''
assert needle in s
s=s.replace(needle,repl,1)
needle="""      if (feedback) feedback.classList.add('hidden');
      list.innerHTML = jobs.length ? jobs.map(renderJob).join('') :"""
repl="""      if (feedback) {
        if (evaluationErrorMessage) {
          feedback.textContent=evaluationErrorMessage;
          feedback.classList.remove('hidden');
        } else feedback.classList.add('hidden');
      }
      list.innerHTML = jobs.length ? jobs.map(renderJob).join('') :"""
assert needle in s
s=s.replace(needle,repl,1)
needle="""    if(!button || button.disabled || busy) return;
    const job=Number(button.dataset.jobId)"""
repl="""    if(!button || button.disabled || busy) return;
    evaluationErrorMessage='';
    const job=Number(button.dataset.jobId)"""
assert needle in s
s=s.replace(needle,repl,1)
needle="""      } catch(err) {if(feedback){feedback.textContent=err.message;feedback.classList.remove('hidden');}}
      finally {busy=false;await update();}
      return;
    }
    if(command==='new' && kind==='evaluation')"""
repl="""      } catch(err) {
        evaluationErrorMessage=err.message;
        if(feedback){feedback.textContent=err.message;feedback.classList.remove('hidden');}
      }
      finally {busy=false;await update();}
      return;
    }
    if(command==='new' && kind==='evaluation')"""
assert needle in s
s=s.replace(needle,repl,1)
p.write_text(s)
print('Added frozen/current model distinctions and persistent actionable error messages')
