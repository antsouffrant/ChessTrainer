// Explicit destructive action; never run from a navigation link.
(() => {
  document.addEventListener('click', async event => {
    const button=event.target.closest('[data-delete-job]');
    if (!button) return;
    const card=button.closest('[data-home-job]');
    const job=Number(button.dataset.deleteJob);
    const title=card?.querySelector('.game-list-index-label strong')?.textContent?.trim() || `#${job}`;
    if (!Number.isSafeInteger(job) || !job) return;
    if (!window.confirm(`Delete game list ${title}?\n\nThis deletes its downloaded batch, positions, coaching cache, evaluation runs, and analysis data. Historical feedback records remain in the independent feedback ledger. This cannot be undone.`)) return;
    button.disabled=true;
    try {
      const response=await fetch(`/api/jobs/${job}/delete`, {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:'DELETE GAME LIST'})});
      const data=await response.json();
      if (!response.ok) throw new Error(data.error||'Deletion failed');
      for (const key of [`pct-training-${job}`]) localStorage.removeItem(key);
      card?.remove();
      if (!document.querySelector('[data-home-job]')) window.location.reload();
    } catch(error) { window.alert(error.message||'Could not delete this game list');button.disabled=false; }
  });
})();
