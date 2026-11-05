import { describe, expect, it } from 'vitest';
import { withComment } from './profile';

describe('withComment', () => {
  it('replaces only the text of a generated COMMENT ON statement', () => {
    expect(withComment("COMMENT ON TABLE `c`.`s`.`t` IS 'old'", "Orders by customer's region")).toBe(
      "COMMENT ON TABLE `c`.`s`.`t` IS 'Orders by customer\\'s region'"
    );
    expect(withComment("COMMENT ON COLUMN `c`.`s`.`t`.`a``b` IS 'x'", 'New')).toBe(
      "COMMENT ON COLUMN `c`.`s`.`t`.`a``b` IS 'New'"
    );
  });

  it('refuses other statements and empty or long text', () => {
    expect(() => withComment('ALTER TABLE `c`.`s`.`t` ADD CONSTRAINT x PRIMARY KEY (a)', 'x')).toThrow();
    expect(() => withComment("COMMENT ON TABLE `c`.`s`.`t` IS 'x'; DROP TABLE y", 'x')).toThrow();
    expect(() => withComment("COMMENT ON TABLE `c`.`s`.`t` IS 'x'", '  ')).toThrow();
    expect(() => withComment("COMMENT ON TABLE `c`.`s`.`t` IS 'x'", 'a'.repeat(1001))).toThrow();
  });
});
