import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveCourseView, courseTabHref } from "../../src/lib/course-navigation";
import CourseNavigation from "../../src/components/CourseNavigation";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("compatible course workspace navigation", () => {
  it.each(["view=materials", "doc=d1", "audio=a1", "section=documents", "view=overview&doc=d1"])("reveals the requested materials for %s", query => {
    expect(resolveCourseView(new URLSearchParams(query))).toBe("materials");
  });
  it("uses Overview for the plain course URL without inventing a material selection", () => {
    expect(resolveCourseView(new URLSearchParams())).toBe("overview");
  });
  it("keeps saved tool route families and the new Materials destination separate", () => {
    expect(courseTabHref("course-1", "materials")).toBe("/course/course-1?view=materials");
    expect(courseTabHref("course-1", "overview")).toBe("/course/course-1");
    expect(courseTabHref("course-1", "exam")).toBe("/course/course-1/exam");
    expect(courseTabHref("course-1", "summary")).toBe("/course/course-1/summary");
  });
  it("keeps the selected destination visible when opening a deep tool URL or changing tabs", () => {
    const scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
    const view = render(<CourseNavigation courseId="course-1" activeTab="tutor" />);
    expect(scroll).toHaveBeenCalledWith({ block: "nearest", inline: "nearest", behavior: "auto" });
    expect(scroll.mock.instances[0]).toBe(view.container.querySelector('a[href="/course/course-1/tutor"]'));
    view.rerender(<CourseNavigation courseId="course-1" activeTab="summary" />);
    expect(scroll.mock.instances.at(-1)).toBe(view.container.querySelector('a[href="/course/course-1/summary"]'));
  });
});
