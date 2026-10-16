const settingsForm = document.querySelector('.settings-form');
const saveStatus = document.getElementById('settings-save-status');
const resetButton = document.getElementById('reset-settings-button');
const pendingTimers = new Map();
const activeJobId = Number(settingsForm?.dataset.jobId || 0) || null;
const learningModeDetails = document.getElementById('learning-mode-multiselect');
const learningModeSummary = document.getElementById('learning-mode-summary');
const learningModeInputs = [...document.querySelectorAll('[data-learning-mode]')];
let learningModeTimer = null;

const modeLabels = {
  mistakes: 'Consequential mistakes', blunders: 'Smaller blunders',
  excellent: 'Correct / excellent moves',
  brilliant: 'Creative / brilliant'
};
const modeSettingKeys = {
  mistakes: 'learning_mode_mistakes',
  blunders: 'learning_mode_blunders',
  excellent: 'learning_mode_excellent',
  brilliant: 'learning_mode_brilliant'
};

function setStatus(message, state = '') {
  if (!saveStatus) return;
  saveStatus.textContent = message;
  saveStatus.dataset.state = state;
}

function valueFor(input) {
  return input.type === 'checkbox' ? input.checked : input.value;
}

function applyImmediateSetting(key, value) {
  if (key === 'show_square_coordinates') {
    document.body.classList.toggle('show-coordinates', Boolean(value));
    window.localStorage.setItem('pct_show_square_coordinates', value ? '1' : '0');
  }
  if (key === 'wooden_board_enabled') {
    document.body.classList.toggle('theme-wood', Boolean(value));
    window.localStorage.setItem('pct_wooden_board_enabled', value ? '1' : '0');
  }
}

async function persist(input) {
  const key = input.dataset.settingKey;
  if (!key) return;
  const value = valueFor(input);
  applyImmediateSetting(key, value);
  setStatus('Saving…', 'saving');
  const row = input.closest('.setting-row');
  row?.classList.add('saving');
  try {
    const response = await fetch(`/api/settings/${encodeURIComponent(key)}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({value, job_id: activeJobId})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save setting');
    setStatus(result.game_list ? (result.game_list.status === 'queued' ? 'Saved · game list re-analysis queued' : 'Saved to game list') : 'Saved', 'saved');
    row?.classList.add('saved');
    window.setTimeout(() => row?.classList.remove('saved'), 700);
  } catch (error) {
    setStatus(error.message || 'Save failed', 'error');
  } finally {
    row?.classList.remove('saving');
  }
}

function selectedLearningModes() {
  return learningModeInputs.filter(input => input.checked && !input.disabled).map(input => input.dataset.learningMode);
}

function updateLearningModeSummary() {
  if (!learningModeSummary) return;
  if (learningModeDetails?.dataset.disabled === '1') {
    learningModeSummary.textContent = 'Opposition research · fixed mode';
    return;
  }
  const selected = selectedLearningModes();
  learningModeSummary.textContent = selected.length ? selected.map(mode => modeLabels[mode]).join(', ') : 'Choose learning modes';
}

async function persistLearningModes() {
  const modes = selectedLearningModes();
  if (!modes.length) {
    setStatus('Keep at least one learning mode enabled', 'error');
    updateLearningModeSummary();
    return;
  }
  setStatus(activeJobId ? 'Saving game-list modes…' : 'Saving learning modes…', 'saving');
  try {
    if (activeJobId) {
      const response = await fetch(`/api/jobs/${activeJobId}/learning-modes`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({modes, persist_defaults: true})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save learning modes');
      setStatus(result.reanalysis_queued ? 'Saved · re-analysis queued' : (result.status === 'paused' ? 'Saved · applies when analysis resumes' : 'Saved to game list'), 'saved');
    } else {
      for (const mode of Object.keys(modeSettingKeys)) {
        const response = await fetch(`/api/settings/${encodeURIComponent(modeSettingKeys[mode])}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({value: modes.includes(mode)})
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not save learning modes');
      }
      setStatus('Saved', 'saved');
    }
  } catch (error) {
    setStatus(error.message || 'Save failed', 'error');
  }
}

function scheduleLearningModes(event) {
  if (!selectedLearningModes().length) {
    if (event?.target) event.target.checked = true;
    setStatus('Keep at least one learning mode enabled', 'error');
  }
  updateLearningModeSummary();
  if (!selectedLearningModes().length) return;
  if (learningModeTimer) window.clearTimeout(learningModeTimer);
  learningModeTimer = window.setTimeout(persistLearningModes, 350);
}

function schedule(input) {
  const key = input.dataset.settingKey;
  if (!key) return;
  const prior = pendingTimers.get(key);
  if (prior) window.clearTimeout(prior);
  if (input.type === 'checkbox') {
    persist(input);
    return;
  }
  pendingTimers.set(key, window.setTimeout(() => persist(input), 450));
}

settingsForm?.querySelectorAll('[data-setting-key]').forEach(input => {
  input.addEventListener('change', () => schedule(input));
  if (input.type === 'text' || input.type === 'number') input.addEventListener('input', () => schedule(input));
});

learningModeInputs.forEach(input => input.addEventListener('change', event => scheduleLearningModes(event)));
learningModeDetails?.addEventListener('toggle', () => {
  if (learningModeDetails.dataset.disabled === '1' && learningModeDetails.open) learningModeDetails.open = false;
});
updateLearningModeSummary();

resetButton?.addEventListener('click', async () => {
  if (!window.confirm('Restore all settings to application defaults?')) return;
  setStatus('Restoring defaults…', 'saving');
  try {
    const response = await fetch('/api/settings/reset', {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not restore defaults');
    for (const input of settingsForm.querySelectorAll('[data-setting-key]')) {
      const key = input.dataset.settingKey;
      if (!(key in result.values)) continue;
      if (input.type === 'checkbox') input.checked = Boolean(result.values[key]);
      else input.value = result.values[key];
    }
    for (const input of learningModeInputs) {
      const key = modeSettingKeys[input.dataset.learningMode];
      if (key in result.values) input.checked = Boolean(result.values[key]);
    }
    updateLearningModeSummary();
    document.body.classList.toggle('theme-wood', Boolean(result.values.wooden_board_enabled));
    window.localStorage.setItem('pct_wooden_board_enabled', result.values.wooden_board_enabled ? '1' : '0');
    setStatus('Defaults restored', 'saved');
  } catch (error) {
    setStatus(error.message || 'Restore failed', 'error');
  }
});

settingsForm?.addEventListener('submit', event => event.preventDefault());
