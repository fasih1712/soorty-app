from django import forms

DEPT_CHOICES = [
    ('', '-- Select Department --'),
    (10, 'ACCOUNTING - NEW YORK'),
    (20, 'RESEARCH - DALLAS'),
    (30, 'SALES - CHICAGO'),
    (40, 'OPERATIONS - BOSTON'),
]

JOB_CHOICES = [
    ('', '-- Select Job --'),
    ('CLERK', 'Clerk'),
    ('SALESMAN', 'Salesman'),
    ('MANAGER', 'Manager'),
    ('ANALYST', 'Analyst'),
    ('PRESIDENT', 'President'),
]

class EmpForm(forms.Form):
    ename    = forms.CharField(label='Employee Name', max_length=50,
                widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. JOHN SMITH'}))
    job      = forms.ChoiceField(label='Job Title', choices=JOB_CHOICES,
                widget=forms.Select(attrs={'class': 'form-select'}))
    mgr      = forms.IntegerField(label='Manager Employee No', required=False,
                widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 7839'}))
    hiredate = forms.DateField(label='Hire Date',
                widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    sal      = forms.DecimalField(label='Salary', max_digits=10, decimal_places=2,
                widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 3000.00'}))
    comm     = forms.DecimalField(label='Commission', required=False, max_digits=10, decimal_places=2,
                widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 500.00'}))
    deptno   = forms.ChoiceField(label='Department', choices=DEPT_CHOICES,
                widget=forms.Select(attrs={'class': 'form-select'}))