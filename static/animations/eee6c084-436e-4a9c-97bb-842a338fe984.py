from manim import *

class CognitiveDebuggerScene(Scene):
    def construct(self):
        # Act 1: Physics diagram
        ladder = Line(ORIGIN, 4 * RIGHT).rotate(60 * DEGREES)
        wall = Rectangle(width=0.5, height=6, color=BLUE).shift(4 * RIGHT + 3 * UP)
        floor = Line(-5 * RIGHT, 5 * RIGHT)
        person = Dot(3 * RIGHT).rotate(60 * DEGREES)
        self.add(ladder, wall, floor, person)
        self.play(Create(ladder), Create(wall), Create(floor), Create(person))
        self.wait(0.5)
        self.play(FadeOut(*self.mobjects))
        self.wait(0.3)

        # Act 2: Solution steps
        eq1 = MathTex(r'\sum F_x = 0')
        eq2 = MathTex(r'\sum F_y = 0')
        eq3 = MathTex(r'\sum M_O = 0')
        self.play(Write(eq1))
        self.wait(0.5)
        self.play(Write(eq2))
        self.wait(0.5)
        self.play(Write(eq3))
        self.wait(0.5)
        self.play(FadeOut(*self.mobjects))
        self.wait(0.3)

        # Act 3: Misconception highlight
        error_text = Text("Incorrect FBD", color=RED)
        incorrect_ladder = Line(ORIGIN, 4 * RIGHT).rotate(60 * DEGREES)
        self.play(Create(incorrect_ladder), Write(error_text))
        self.play(Indicate(incorrect_ladder))
        self.wait(0.5)