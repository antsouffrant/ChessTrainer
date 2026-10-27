"""Browser regression test for mouse/touch drag and click-to-move.

Run with: python tests/test_dual_board_input_v41.py
Requires Playwright and a Chromium binary; no Flask or Stockfish required.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / 'tests' / '_board_input_fixture_v41.html'
HTML.write_text('''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
#board {display:grid;grid-template-columns:repeat(2,90px);width:180px;touch-action:manipulation}
.square{width:90px;height:90px;display:grid;place-items:center;background:#ddd;}
.square:nth-child(even){background:#888}
.piece{display:grid;place-items:center;width:55px;height:55px;background:lightblue;touch-action:none;user-select:none;}
.dragging-piece-ghost {position:fixed !important;z-index:1000;display:grid;place-items:center;pointer-events:none;touch-action:none}
</style></head><body>
<div id="board" tabindex="0">
  <div class="square" data-square="e2"><span class="piece" id="piece">♞</span></div>
  <div class="square" data-square="e4"></div>
  <div class="square" data-square="d2"></div>
  <div class="square" data-square="d4"></div>
</div>
<script src="../static/board_pointer_drag.js"></script><script>
const board = document.getElementById('board');
let chosen=null;
window.moves=[];
window.reset=()=>{
  chosen=null;window.moves=[];
  document.querySelector('[data-square="e2"]').append(document.querySelector('#piece'));
};
function move(from,to){if(to==='e4' && from==='e2'){window.moves.push(from+to);document.querySelector('[data-square="e4"]').append(document.querySelector('#piece'));}}
board.addEventListener('click',ev=>{
  const square=ev.target.closest('.square');if(!square)return;
  if(square.dataset.square==='e2'){chosen='e2';return;}
  if(chosen) {move(chosen,square.dataset.square);chosen=null;}
});
const controller=window.installBoardPointerDrag(board, {
  canStart:from=>from==='e2' && document.querySelector('#piece').parentElement.dataset.square==='e2',
  onStart:from=>{chosen=from;},
  onDrop:(from,to)=>{chosen=null;move(from,to)},
  onCancel:()=>{chosen=null;}
});
</script></body></html>''', encoding='utf-8')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':800,'height':600}, has_touch=True)
    page.set_content(HTML.read_text(encoding="utf-8").split('<script src="../static/board_pointer_drag.js"></script>')[0] + "</body></html>")
    page.add_script_tag(path=str(ROOT / "static" / "board_pointer_drag.js"))
    page.evaluate("""() => {
      const board = document.getElementById('board');
      let chosen = null; window.moves = [];
      window.reset = () => { chosen = null; window.moves = []; document.querySelector('[data-square="e2"]').append(document.getElementById('piece')); };
      function move(from,to) { if (from === 'e2' && to === 'e4') { window.moves.push(from + to); document.querySelector('[data-square="e4"]').append(document.getElementById('piece')); } }
      board.addEventListener('click', e => { const square = e.target.closest('.square'); if (!square) return; if (square.dataset.square === 'e2') { chosen = 'e2'; return; } if (chosen) { move(chosen, square.dataset.square); chosen = null; } });
      window.installBoardPointerDrag(board, { canStart: from => from === 'e2' && document.getElementById('piece').parentElement.dataset.square === 'e2', onStart: from => { chosen = from; }, onDrop: (from, to) => { chosen = null; move(from, to); }, onCancel: () => { chosen = null; } });
    }""")
    src = page.locator('#piece')
    dst = page.locator('[data-square="e4"]')
    start = src.bounding_box()
    end = dst.bounding_box()
    page.mouse.move(start['x']+start['width']/2, start['y']+start['height']/2)
    page.mouse.down()
    page.mouse.move(end['x']+end['width']/2, end['y']+end['height']/2, steps=8)
    page.mouse.up()
    assert page.evaluate('window.moves') == ['e2e4'], f'mouse drag failed: {page.evaluate("window.moves")}'
    print('PASS: mouse drag -> legal move')
    page.evaluate('reset()')
    src.click()
    dst.click()
    assert page.evaluate('window.moves') == ['e2e4'], f'click-to-move failed: {page.evaluate("window.moves")}'
    print('PASS: click piece, then destination')
    page.evaluate('reset()')
    # CDP sends real touch pointer events (not simulated DOM-only events).
    cdp = page.context.new_cdp_session(page)
    start = page.locator('#piece').bounding_box()
    end = dst.bounding_box()
    x0,y0=start['x']+start['width']/2,start['y']+start['height']/2
    x1,y1=end['x']+end['width']/2,end['y']+end['height']/2
    cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':x0,'y':y0,'id':1}]})
    for i in range(1,9):
        cdp.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':x0+(x1-x0)*i/8,'y':y0+(y1-y0)*i/8,'id':1}]})
    cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
    assert page.evaluate('window.moves') == ['e2e4'], f'touch drag failed: {page.evaluate("window.moves")}'
    print('PASS: touch drag -> legal move')
    page.evaluate('reset()')
    # An illegal target must never be submitted. A later click move still works.
    src = page.locator('#piece'); invalid = page.locator('[data-square="d4"]')
    b=src.bounding_box(); c=invalid.bounding_box()
    page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2)
    page.mouse.down(); page.mouse.move(c['x']+c['width']/2,c['y']+c['height']/2,steps=8); page.mouse.up()
    assert page.evaluate('window.moves') == [], 'illegal drag submitted a move'
    src.click(); dst.click()
    assert page.evaluate('window.moves') == ['e2e4'], 'click stopped working after invalid drag'
    print('PASS: invalid drop ignored; click input remains available')
    browser.close()
HTML.unlink(missing_ok=True)
