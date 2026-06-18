

function changeVisibility(element) {
	if (typeof element === "string") {
		element = document.getElementById(element);
	}
	if (element) {
		element.hidden = !(element.hidden);
	} else {
		console.log("In changeVisibility: element not found");
	}
}

function countVars(className, targetId) {

	// count all checked variables
	let els = document.querySelectorAll(`.${className}:checked`);
	console.log(els.length);

	// chenge visisble count
	let targetEl = document.getElementById(targetId);
	targetEl.innerHTML = els.length;

	let secondPart = document.getElementById('step-2');
	if (els.length > 0 && secondPart.hidden) {
		changeVisibility(secondPart);
	}
	if (els.length == 0 && !secondPart.hidden) {
		changeVisibility(secondPart);
	}

}


function checkOnetoOne(variableId) {
	let el = document.getElementById(`poser-${variableId}`);
	let targetEl = document.getElementById(`actual-${variableId}`);
	console.log(el.checked);

	targetEl.checked = el.checked;
	console.log(targetEl.checked);
}




function getVariables() {

    console.log("in sending");

    let targetEl = document.getElementById("variables-place");

    let formElement = document.getElementById('search-form');
    let url = formElement.dataset.url;

    console.log(url);

    let formValues = htmx.values(formElement);
    console.log(formValues);

    let prom = htmx.ajax('POST', url, {target : targetEl, swap : 'innerHTML', source : formElement, values: formValues});
    prom.then(function () {
        console.log("after promise");
    })

}

function getPlot() {
    console.log("in getting plot");

    let formElement = document.getElementById('vars-form');
    let url = formElement.dataset.url;

    console.log(url);

    let formValues = htmx.values(formElement);
    console.log(formValues);

    let prom = htmx.ajax('POST', url, {source : formElement, values: formValues});
    prom.then(function () {
        console.log("after promise");
    })
    
}

// function selectAllInDataset(datasetBlockId) {
//     let datasetBlock = document.getElementById(datasetBlockId);
    
//     let checkboxes = datasetBlock.querySelectorAll('.variable-choice');
    
//     checkboxes.forEach(function(checkbox) {
//         checkbox.checked = true;

//         let variableId = checkbox.id.replace('poser-', '');
//         checkOnetoOne(variableId);
//     });
    
//     countVars('variable-choice', 'var-count');
// }

// function deselectAllInDataset(datasetBlockId) {
//     let datasetBlock = document.getElementById(datasetBlockId);
    
//     let checkboxes = datasetBlock.querySelectorAll('.variable-choice');
    
//     checkboxes.forEach(function(checkbox) {
//         checkbox.checked = false;

//         let variableId = checkbox.id.replace('poser-', '');
//         checkOnetoOne(variableId);
//     });
    
//     countVars('variable-choice', 'var-count');
// }

function setCheckboxesInContainer(containerId, checked) {
    let container = document.getElementById(containerId);

    if (!container) {
        console.log(`Container not found: ${containerId}`);
        return;
    }

    let checkboxes = container.querySelectorAll('.variable-choice');

    checkboxes.forEach(function(checkbox) {
        checkbox.checked = checked;

        let variableId = checkbox.id.replace('poser-', '');
        checkOnetoOne(variableId);
    });

    countVars('variable-choice', 'var-count');
}

function selectAllInDataset(datasetBlockId) {
    setCheckboxesInContainer(datasetBlockId, true);
}

function deselectAllInDataset(datasetBlockId) {
    setCheckboxesInContainer(datasetBlockId, false);
}

function selectAllInContainer(containerId) {
    setCheckboxesInContainer(containerId, true);
}

function deselectAllInContainer(containerId) {
    setCheckboxesInContainer(containerId, false);
}