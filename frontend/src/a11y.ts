// Associates every `.field > label` (written without `for`) with the first control in the same field,
// so inputs/selects/textarea get a proper accessible name and clicking the label focuses the control.
let n = 0
function link(root: ParentNode) {
  root.querySelectorAll<HTMLLabelElement>('.field > label:not([for]), .lbl-row > label:not([for])').forEach((label) => {
    const scope = label.closest('.field') || label.parentElement
    const ctl = scope?.querySelector<HTMLElement>('input:not([type="hidden"]):not([type="checkbox"]):not([type="range"]), select, textarea')
    if (!ctl || ctl.hasAttribute('aria-label') || ctl.hasAttribute('aria-labelledby')) return
    if (!ctl.id) ctl.id = 'f-' + ++n
    label.htmlFor = ctl.id
  })
}
export function installLabelLinker() {
  link(document)
  new MutationObserver(() => link(document)).observe(document.body, { childList: true, subtree: true })
}
