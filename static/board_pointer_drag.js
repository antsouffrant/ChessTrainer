/* Chessboard drag input.  Mouse, pen and touch all use the same pointer path.
   A short tap remains a normal click, so click-piece/click-square still works. */
(function (root) {
  'use strict';

  function installBoardPointerDrag(board, options) {
    if (!board) return {cancel() {}, destroy() {}};
    let gesture = null;
    let ghost = null;
    let suppressClick = false;
    let suppressTimer = null;

    function removeGhost() {
      if (gesture?.piece?.isConnected) gesture.piece.style.opacity = gesture.originalOpacity;
      if (ghost) ghost.remove();
      ghost = null;
      board.classList.remove('piece-dragging');
    }
    function cancel() {
      removeGhost();
      gesture = null;
    }
    function renderGhost(e) {
      if (!gesture || ghost) return;
      const rect = gesture.square.getBoundingClientRect();
      ghost = gesture.piece.cloneNode(true);
      ghost.removeAttribute('id');
      ghost.classList.add('dragging-piece-ghost');
      ghost.draggable = false;
      ghost.style.width = `${rect.width}px`;
      ghost.style.height = `${rect.height}px`;
      ghost.style.fontSize = getComputedStyle(gesture.piece).fontSize;
      document.body.appendChild(ghost);
      gesture.piece.style.opacity = '.28';
      board.classList.add('piece-dragging');
      options.onStart?.(gesture.from);
      moveGhost(e);
    }
    function moveGhost(e) {
      if (!ghost) return;
      const w = parseFloat(ghost.style.width) || 0;
      const h = parseFloat(ghost.style.height) || 0;
      ghost.style.left = `${e.clientX - w / 2}px`;
      ghost.style.top = `${e.clientY - h / 2}px`;
    }
    function onPointerDown(e) {
      // A new press is an intentional interaction, not the synthetic click
      // emitted after the previous drag's pointerup.
      suppressClick = false;
      clearTimeout(suppressTimer);
      // Do not hijack right-click, review buttons, or non-playable pieces.
      if (gesture || (e.pointerType === 'mouse' && e.button !== 0)) return;
      const piece = e.target.closest?.('.piece');
      const square = e.target.closest?.('.square');
      if (!piece || !square || !board.contains(square)) return;
      const from = square.dataset.square;
      if (!options.canStart(from)) return;
      gesture = {
        pointerId: e.pointerId, from, square, piece,
        originalOpacity: piece.style.opacity,
        x: e.clientX, y: e.clientY, dragging: false
      };
      // No preventDefault here: a tap must generate the ordinary click event.
    }
    function onPointerMove(e) {
      if (!gesture || gesture.pointerId !== e.pointerId) return;
      if (!options.canStart(gesture.from)) { cancel(); return; }
      if (!gesture.dragging) {
        const distance = Math.hypot(e.clientX - gesture.x, e.clientY - gesture.y);
        if (distance < (e.pointerType === 'touch' ? 10 : 6)) return;
        gesture.dragging = true;
        renderGhost(e);
      }
      if (e.cancelable) e.preventDefault();
      moveGhost(e);
    }
    function onPointerUp(e) {
      if (!gesture || gesture.pointerId !== e.pointerId) return;
      const wasDragging = gesture.dragging;
      const from = gesture.from;
      let to = null;
      if (wasDragging) {
        // Unlike e.target, elementFromPoint is not affected by pointer capture
        // or by the mouse being released over a child piece/coordinate label.
        const square = document.elementFromPoint(e.clientX, e.clientY)?.closest?.('.square');
        if (square && board.contains(square)) to = square.dataset.square;
      }
      cancel();
      if (!wasDragging) return; // A normal tap is handled by board click.
      if (e.cancelable) e.preventDefault();
      suppressClick = true;
      clearTimeout(suppressTimer);
      suppressTimer = setTimeout(() => { suppressClick = false; }, 100);
      if (to && to !== from) options.onDrop(from, to);
      else options.onCancel?.();
      board.focus({preventScroll: true});
    }
    function onPointerCancel(e) {
      if (!gesture || gesture.pointerId !== e.pointerId) return;
      const wasDragging = gesture.dragging;
      cancel();
      if (wasDragging) options.onCancel?.();
    }
    function onClickCapture(e) {
      if (!suppressClick) return;
      suppressClick = false;
      clearTimeout(suppressTimer);
      e.preventDefault();
      e.stopImmediatePropagation();
    }
    board.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove, {passive: false});
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerCancel);
    window.addEventListener('blur', cancel);
    board.addEventListener('click', onClickCapture, true);
    return {
      cancel,
      destroy() {
        cancel();
        clearTimeout(suppressTimer);
        board.removeEventListener('pointerdown', onPointerDown);
        window.removeEventListener('pointermove', onPointerMove);
        window.removeEventListener('pointerup', onPointerUp);
        window.removeEventListener('pointercancel', onPointerCancel);
        window.removeEventListener('blur', cancel);
        board.removeEventListener('click', onClickCapture, true);
      }
    };
  }

  root.installBoardPointerDrag = installBoardPointerDrag;
})(window);
