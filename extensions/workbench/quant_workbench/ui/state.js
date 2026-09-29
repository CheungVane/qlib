// Client navigation state, independent of DOM and network.
export function createState(location) {
const initialQuery = new URLSearchParams(location.search);
const hasCompareQuery = initialQuery.has('compare');
const historyTabParam = initialQuery.get('history');
const state = {renderGeneration:0, revision: initialQuery.get("revision"), seriesOffsets:{}, runs: [], selected: initialQuery.get('run'), compareIds: (initialQuery.get('compare') || '').split(',').filter(Boolean), researchId: initialQuery.get('research'), researchOffset:0, researchQuery:'', search: '', executionKey:null, executionKind:null, helpTrigger:null, helpBound:false, historyTab: historyTabParam==='research'?'research':'attempts', historyExpanded:false, historyScrollTop:0, attemptCursor:null, attemptCursors:[], runsExpanded:false, overviewExpanded:false, factorGroup:null, paletteIndex:null, paletteFetchedAt:0, paletteSelection:0, paletteResults:[], paletteScope:'', paletteBound:false, view: location.hash.slice(1) || (initialQuery.has('run')||hasCompareQuery||initialQuery.has('research')?'overview':'factors')};
 return {state, hasCompareQuery};
}
