/** @odoo-module **/

export const ACCENTS = ["primary", "success", "info", "warning", "danger", "purple"];


export const defaultPipeline = {
    totalCount: 0,
    newCount: 0,
    doneCount: 0,
    canceledCount: 0,
    inProgressCount: 0,
}


export async function fetchDataTasksCount(orm, userId) {
    // 1️⃣ Group by stage
    const grouped = await orm.readGroup(
        "project.task",
        [["user_ids", "in", [userId]]],
        ["__count", "effective_hours:sum"],
        ["stage_id", "project_id"],
        {lazy: false}
    );


    const projectMap = {};


    for (const row of grouped) {

        const projectId = row.project_id?.[0] || 0;
        const projectName = row.project_id?.[1] || 'No Project';
        const stageName = row.stage_id?.[1]?.toLowerCase();
        const count = row.__count || 0;
        const hours = row?.effective_hours || 0;


        if (!projectMap[projectId]) {
            projectMap[projectId] = {
                id: projectId,
                name: projectName,
                taskCount: 0, // (total) tasks count
                totalHours: 0, // total hours spent on tasks
                openTasks: 0,  // (open) tasks not in new/done/canceled/progress stages
                completedTasks: 0, // (done) tasks count
                canceledTasks: 0, // (canceled) tasks count
                inProgressTasks: 0,
                newTasks: 0,
                completionPercentage: 0,
                accent: "",
            };
        }

        const project = projectMap[projectId];

        project.taskCount += count;
        project.totalHours += hours;

        if (!stageName) {
            project.openTasks += count;
        } else if (stageName.includes("cancel")) {
            project.canceledTasks += count;
        } else if (stageName.includes("done")) {
            project.completedTasks += count;
        } else if (stageName.includes("progress")) {
            project.inProgressTasks += count;
        } else if (stageName.includes("new")) {
            project.newTasks += count;
        } else {
            project.openTasks += count;
        }
    }

    const project = Object.values(projectMap);

    const pipeline = defaultPipeline;
    project.forEach((p, idx) => {
        p.accent = ACCENTS[idx % ACCENTS.length];
        p.completionPercentage = p.taskCount
            ? Math.round((p.completedTasks / p.taskCount) * 100)
            : 0;

        pipeline.totalCount += p.taskCount;
        pipeline.newCount += p.newTasks;
        pipeline.doneCount += p.completedTasks;
        pipeline.canceledCount += p.canceledTasks;
        pipeline.inProgressCount += p.inProgressTasks;
        // p.totalHours = Math.round(p.totalHours * 10) / 10;
    });


    return {
        project,
        pipeline,
    };
}

export async function getDeadlinesTasks(orm, userId) {
    const tasks = await orm.searchRead(
        "project.task",
        [
            ["user_ids", "in", [userId]],
            ["is_closed", "=", false],
        ],
        ["date_deadline"]
    );

    const today = new Date().toISOString().split("T")[0];

    let delayed = 0;
    let todayCount = 0;
    let upcoming = 0;
    let noDeadline = 0;

    for (const task of tasks) {
        const deadline = task.date_deadline;

        if (!deadline) {
            noDeadline++;
        } else if (deadline < today) {
            delayed++;
        } else if (deadline === today) {
            todayCount++;
        } else {
            upcoming++;
        }
    }

    return {
        delayed,
        todayCount,
        upcoming,
        noDeadline,
    }

}

export async function fetchTaskDashboard(orm, userId) {
    const {
        project = [],
        pipeline = defaultPipeline
    } = await fetchDataTasksCount(orm, userId);

    const deadlines = await getDeadlinesTasks(orm, userId);
    return {
        projects: project,
        pipeline,
        deadlines
    }
}
