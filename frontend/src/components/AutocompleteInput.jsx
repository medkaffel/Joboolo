import React, { useState, useRef, useEffect } from 'react';
import { jobService } from '../services/jobService';
import { geoService } from '../services/geoService';

// Autocomplete text input. For field='location' suggestions come from the French
// cities/departments/regions (geo.api.gouv.fr); otherwise from DB suggestions.
// props: value, onChange(val), onSelect(val), field ('title'|'location'|'company'), icon, placeholder, testId
const AutocompleteInput = ({ value, onChange, onSelect, field = 'title', icon: Icon, placeholder, testId, inputClassName }) => {
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const boxRef = useRef(null);
  const timer = useRef(null);

  useEffect(() => {
    const onDocClick = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  const handleChange = (val) => {
    onChange(val);
    setActive(-1);
    clearTimeout(timer.current);
    if (val.trim().length < 2) { setSuggestions([]); setOpen(false); return; }
    timer.current = setTimeout(async () => {
      let res;
      if (field === 'location') {
        res = await geoService.autocomplete(val); // [{value,label,type}]
      } else {
        const raw = await jobService.suggest(val, field); // [string]
        res = raw.map((s) => ({ value: s, label: s }));
      }
      setSuggestions(res);
      setOpen(res.length > 0);
    }, 200);
  };

  const pick = (s) => {
    onChange(s.value);
    setOpen(false);
    setSuggestions([]);
    if (onSelect) onSelect(s.value);
  };

  const onKeyDown = (e) => {
    if (!open) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, suggestions.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); pick(suggestions[active]); }
    else if (e.key === 'Escape') { setOpen(false); }
  };

  return (
    <div className="relative flex-1 flex items-center" ref={boxRef}>
      {Icon && <Icon className="absolute left-4 h-5 w-5 text-slate-400 pointer-events-none" />}
      <input
        type="text"
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        onFocus={() => suggestions.length && setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoComplete="off"
        className={inputClassName || 'w-full h-12 md:h-14 pl-12 pr-4 bg-transparent rounded-full text-slate-900 placeholder:text-slate-400 focus:outline-none'}
        data-testid={testId}
      />
      {open && suggestions.length > 0 && (
        <ul className="absolute top-full left-0 right-0 mt-1 bg-white rounded-2xl shadow-xl border border-slate-100 py-2 z-50 max-h-72 overflow-auto" data-testid={`${testId}-suggestions`}>
          {suggestions.map((s, i) => (
            <li key={i}>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); pick(s); }}
                className={`w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-brand/5 ${i === active ? 'bg-brand/5' : ''}`}
                data-testid={`${testId}-option-${i}`}
              >
                {s.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default AutocompleteInput;
