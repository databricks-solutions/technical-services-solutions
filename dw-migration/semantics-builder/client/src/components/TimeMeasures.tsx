import { useState } from 'react';
import { Alert, Button, Checkbox, Modal, SimpleSelect, SimpleSelectOption } from '@databricks/design-system';
import { renderMetricView, validateMetricView } from '../../../shared/metricView';
import type { MetricView } from '../../../shared/metricView';
import { addTimeIntelligence, grainOf, TIME_KINDS } from '../../../shared/timeIntelligence';
import type { Grain, TimeKind } from '../../../shared/timeIntelligence';

const GRAINS: Grain[] = ['day', 'week', 'month', 'quarter', 'year'];

/** One click time intelligence: window measures for a measure over a date dimension, saved as a new version. */
export function TimeMeasures({
  view,
  disabled,
  onSave,
}: {
  view: MetricView;
  disabled: boolean;
  onSave: (yaml: string) => void;
}) {
  const dates = view.dimensions.filter((d) => grainOf(d.expr, d.name));
  const plain = view.measures.filter((m) => !m.window);
  const [open, setOpen] = useState(false);
  const [measure, setMeasure] = useState(plain[0]?.name ?? '');
  const [dimension, setDimension] = useState(dates[0]?.name ?? '');
  const [grain, setGrain] = useState<Grain>(grainOf(dates[0]?.expr ?? '', dates[0]?.name) ?? 'month');
  const [kinds, setKinds] = useState<TimeKind[]>(['to_date', 'growth']);
  const [problem, setProblem] = useState<string>();
  if (!dates.length || !plain.length) return null;

  const pickDimension = (name: string) => {
    setDimension(name);
    const d = dates.find((x) => x.name === name);
    setGrain(grainOf(d?.expr ?? '', name) ?? 'month');
  };

  const add = () => {
    const out = addTimeIntelligence(view, { measure, dimension, grain, kinds });
    if (!out.added.length) {
      setProblem('These measures exist already.');
      return;
    }
    const yaml = renderMetricView(out.view);
    const errors = validateMetricView(yaml).issues.filter((i) => i.severity === 'error');
    if (errors.length) {
      setProblem(errors.map((e) => e.message).join(' '));
      return;
    }
    setOpen(false);
    onSave(yaml);
  };

  return (
    <>
      <div>
        <Button componentId="gsb.time.open" disabled={disabled} onClick={() => setOpen(true)}>
          Add time measures
        </Button>
      </div>
      <Modal
        componentId="gsb.time.modal"
        title="Add time measures"
        visible={open}
        okText="Add as a new version"
        cancelText="Cancel"
        okButtonProps={{ disabled: !kinds.length }}
        onCancel={() => setOpen(false)}
        onOk={add}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <SimpleSelect
            componentId="gsb.time.measure"
            id="time-measure"
            label="Measure"
            value={measure}
            onChange={(e) => setMeasure(e.target.value)}
          >
            {plain.map((m) => (
              <SimpleSelectOption key={m.name} value={m.name}>
                {m.name}
              </SimpleSelectOption>
            ))}
          </SimpleSelect>
          <SimpleSelect
            componentId="gsb.time.dimension"
            id="time-dimension"
            label="Date dimension"
            value={dimension}
            onChange={(e) => pickDimension(e.target.value)}
          >
            {dates.map((d) => (
              <SimpleSelectOption key={d.name} value={d.name}>
                {d.name}
              </SimpleSelectOption>
            ))}
          </SimpleSelect>
          <SimpleSelect
            componentId="gsb.time.grain"
            id="time-grain"
            label="One row of the dimension is a"
            value={grain}
            onChange={(e) => setGrain(e.target.value as Grain)}
          >
            {GRAINS.map((g) => (
              <SimpleSelectOption key={g} value={g}>
                {g}
              </SimpleSelectOption>
            ))}
          </SimpleSelect>
          <div role="group" aria-label="Time measures" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {TIME_KINDS.map((k) => (
              <Checkbox
                key={k.kind}
                componentId="gsb.time.kind"
                isChecked={kinds.includes(k.kind)}
                onChange={(on) => setKinds(on ? [...kinds, k.kind] : kinds.filter((x) => x !== k.kind))}
              >
                {k.label}
              </Checkbox>
            ))}
          </div>
          {problem && <Alert componentId="gsb.time.problem" type="error" closable={false} message={problem} />}
        </div>
      </Modal>
    </>
  );
}
