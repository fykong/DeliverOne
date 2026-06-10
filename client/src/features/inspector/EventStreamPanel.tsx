import { Terminal } from "lucide-react";
import type { RuntimeEvent } from "@workbench/shared";

interface EventStreamPanelProps {
  events: RuntimeEvent[];
}

export function EventStreamPanel({ events }: EventStreamPanelProps) {
  return (
    <section className="panel">
      <h3>
        <Terminal size={16} />
        事件流
      </h3>
      <div className="eventList">
        {events.slice(-10).map((event) => (
          <div className={`eventRow ${event.actor}`} key={event.id}>
            <span>{event.actor}</span>
            <strong>{event.type}</strong>
            <small>{new Date(event.createdAt).toLocaleTimeString()}</small>
          </div>
        ))}
        {events.length === 0 && <p>还没有 runtime 事件。工具计划执行后会实时留下记录。</p>}
      </div>
    </section>
  );
}
