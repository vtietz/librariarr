export function addRule<T>(rows: T[], create: () => T): T[] {
  return [...rows, create()];
}

export function removeRuleAt<T>(rows: T[], index: number): T[] {
  return rows.filter((_, rowIndex) => rowIndex !== index);
}

export function updateRuleAt<T>(rows: T[], index: number, update: (row: T) => T): T[] {
  return rows.map((row, rowIndex) => {
    if (rowIndex !== index) {
      return row;
    }
    return update(row);
  });
}
