/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";

/**
 * Thin wrapper around the ESS JSON controller endpoints.
 * Every method returns the parsed payload (already a plain object).
 */
export const essApi = {
    dashboard: () => rpc("/my/ess/dashboard", {}),
    leaves: () => rpc("/my/ess/leaves", {}),
    createLeave: (data) => rpc("/my/ess/leave/create", data),
    attendance: () => rpc("/my/ess/attendance", {}),
    payslips: () => rpc("/my/ess/payslips", {}),
    payslipDetail: (slipId) => rpc(`/my/ess/payslip/${slipId}`, {}),
    letters: () => rpc("/my/ess/letters", {}),
    createLetter: (data) => rpc("/my/ess/letter/create", data),
    trips: () => rpc("/my/ess/trips", {}),
    createTrip: (data) => rpc("/my/ess/trip/create", data),
};

// Map a backend state code to a badge accent used by the UI.
export function stateAccent(state) {
    const map = {
        validate: "success",
        approved: "success",
        issued: "success",
        done: "success",
        paid: "success",
        confirm: "warning",
        validate1: "warning",
        submitted: "warning",
        verify: "warning",
        draft: "muted",
        refuse: "danger",
        refused: "danger",
        cancel: "danger",
    };
    return map[state] || "muted";
}

export function fmtMoney(amount, currency) {
    const value = (amount || 0).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
    return currency ? `${currency} ${value}` : value;
}
